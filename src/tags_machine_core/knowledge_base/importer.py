from __future__ import annotations

import hashlib
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml

from tags_machine_core.logging_config import get_logger

from .catalog import CatalogStore
from .config import KnowledgeBaseConfig
from .models import (
    ActionCatalogItem,
    CatalogActionSummary,
    CatalogFiles,
    CatalogManifest,
    CatalogSource,
    CatalogWarning,
    KnowledgeBaseImportResult,
)
from .normalization import normalize_classification, normalize_meta, stable_json_hash

logger = get_logger(__name__)
NODE_FILENAMES = ("tags.txt", "classify.yaml", "meta.yaml")


def import_catalog(config: KnowledgeBaseConfig) -> KnowledgeBaseImportResult:
    started = time.monotonic()
    source_roots, source_issues = config.resolve_source_roots()
    logger.info(
        "knowledge base import config=%s source_roots=%d",
        config.config_path,
        len(source_roots),
    )
    warnings: list[CatalogWarning] = []
    for root_id, relative_path, code in source_issues:
        warnings.append(
            CatalogWarning(
                ref=relative_path,
                code=code,
                message=(
                    f"source {root_id!r} 未找到: {relative_path}"
                    if code == "source_missing"
                    else f"source {root_id!r} 重复命中: {relative_path}"
                ),
                details={"root_id": root_id},
            )
        )

    discovered: list[tuple[str, Path]] = []
    for source_root in source_roots:
        for node_dir in _discover_node_dirs(source_root.path):
            discovered.append((source_root.root_id, node_dir))
    discovered.sort(key=lambda value: value[1].relative_to(config.action_root).as_posix())
    logger.info("knowledge base discovered nodes=%d", len(discovered))

    items: list[ActionCatalogItem] = []
    item_warnings: dict[str, list[CatalogWarning]] = defaultdict(list)
    def read_discovered(entry: tuple[str, Path]):
        root_id, node_dir = entry
        return _read_catalog_item(config=config, root_id=root_id, node_dir=node_dir)

    # 每个动作目录完全独立，线程池主要用于覆盖 Windows 上大量小文件读取延迟。
    with ThreadPoolExecutor() as executor:
        parsed_items = executor.map(read_discovered, discovered)
        for item, current_warnings in parsed_items:
            items.append(item)
            item_warnings[item.ref].extend(current_warnings)
            logger.trace("knowledge base imported ref=%s hash=%s", item.ref, item.files.content_hash)

    _apply_aliases(items, item_warnings)
    _detect_duplicate_prompts(items, item_warnings)
    for item in items:
        item.warnings = _dedupe_preserve([warning.code for warning in item_warnings[item.ref]])
        warnings.extend(item_warnings[item.ref])
    warnings.sort(key=lambda warning: (warning.ref, warning.file or "", warning.code, warning.message))
    items.sort(key=lambda item: item.ref)

    catalog_payload = {
        "items": [item.model_dump(by_alias=True, mode="json") for item in items],
        "warnings": [warning.model_dump(mode="json") for warning in warnings],
    }
    catalog_hash = stable_json_hash(catalog_payload)
    alias_group_count = len({item.alias_group for item in items})
    manifest = CatalogManifest(
        catalog_hash=catalog_hash,
        created_at=datetime.now(UTC).isoformat(),
        action_root=str(config.action_root),
        config_path=str(config.config_path),
        source_roots=[
            {
                "root_id": source_root.root_id,
                "path": source_root.path.relative_to(config.action_root).as_posix(),
            }
            for source_root in source_roots
        ],
        record_count=len(items),
        alias_group_count=alias_group_count,
        warning_count=len(warnings),
    )
    build_dir, reused = CatalogStore.from_config(config).publish(
        catalog_hash=catalog_hash,
        manifest=manifest,
        items=items,
        warnings=warnings,
    )
    warning_counts = Counter(warning.code for warning in warnings)
    if warning_counts:
        logger.warning(
            "knowledge base warnings total=%d summary=%s",
            len(warnings),
            dict(sorted(warning_counts.items())),
        )
    logger.info(
        "knowledge base catalog hash=%s records=%d reused=%s path=%s elapsed=%.2fs",
        catalog_hash,
        len(items),
        reused,
        build_dir,
        time.monotonic() - started,
    )
    return KnowledgeBaseImportResult(
        catalog_hash=catalog_hash,
        build_dir=str(build_dir),
        record_count=len(items),
        alias_group_count=alias_group_count,
        warning_count=len(warnings),
        reused_build=reused,
    )


def _discover_node_dirs(source_root: Path) -> list[Path]:
    result: list[Path] = []
    for current in source_root.rglob("*"):
        if current.is_dir() and any((current / name).is_file() for name in NODE_FILENAMES):
            result.append(current)
    if any((source_root / name).is_file() for name in NODE_FILENAMES):
        result.append(source_root)
    return sorted(set(result), key=lambda path: path.as_posix())


def _read_catalog_item(
    *,
    config: KnowledgeBaseConfig,
    root_id: str,
    node_dir: Path,
) -> tuple[ActionCatalogItem, list[CatalogWarning]]:
    ref = node_dir.relative_to(config.action_root).as_posix()
    warnings: list[CatalogWarning] = []
    file_bytes: dict[str, bytes | None] = {}
    file_hashes: dict[str, str | None] = {}
    file_exists: dict[str, bool] = {}
    for filename in NODE_FILENAMES:
        path = node_dir / filename
        if not path.is_file():
            file_exists[filename] = False
            file_bytes[filename] = None
            file_hashes[filename] = None
            warnings.append(
                CatalogWarning(
                    ref=ref,
                    file=filename,
                    code="missing_file",
                    message=f"缺少 {filename}",
                )
            )
            continue
        file_exists[filename] = True
        try:
            content = path.read_bytes()
        except OSError as exc:
            file_bytes[filename] = None
            file_hashes[filename] = None
            warnings.append(
                CatalogWarning(
                    ref=ref,
                    file=filename,
                    code="parse_error",
                    message=f"无法读取 {filename}: {type(exc).__name__}",
                    details={"errno": getattr(exc, "errno", None)},
                )
            )
            continue
        file_bytes[filename] = content
        file_hashes[filename] = "sha256:" + hashlib.sha256(content).hexdigest()

    classify_raw = _load_yaml(file_bytes["classify.yaml"], ref, "classify.yaml", warnings)
    meta_raw = _load_yaml(file_bytes["meta.yaml"], ref, "meta.yaml", warnings)
    classification, classify_warnings = normalize_classification(classify_raw, ref=ref)
    meta, meta_warnings = normalize_meta(meta_raw, ref=ref)
    warnings.extend(classify_warnings)
    warnings.extend(meta_warnings)

    if isinstance(classify_raw, dict):
        schema_version = classify_raw.get("schema_version")
        if schema_version not in (None, 1, "1"):
            warnings.append(
                CatalogWarning(
                    ref=ref,
                    file="classify.yaml",
                    code="schema_mismatch",
                    message=f"不支持 classify schema_version: {schema_version!r}",
                )
            )
        classify_node_id = str(classify_raw.get("node_id") or "").strip()
        if classify_node_id and classify_node_id not in {ref, node_dir.name}:
            warnings.append(
                CatalogWarning(
                    ref=ref,
                    file="classify.yaml",
                    code="id_mismatch",
                    message=(
                        f"classify node_id {classify_node_id!r} "
                        f"与 ref {ref!r} 不一致"
                    ),
                )
            )
    if meta.schema_id and meta.schema_id != "tags-machine.action/v1":
        warnings.append(
            CatalogWarning(
                ref=ref,
                file="meta.yaml",
                code="schema_mismatch",
                message=f"不支持 meta schema: {meta.schema_id!r}",
            )
        )
    if meta.kind and meta.kind != "action":
        warnings.append(
            CatalogWarning(
                ref=ref,
                file="meta.yaml",
                code="kind_mismatch",
                message=f"meta kind 应为 action，实际为 {meta.kind!r}",
            )
        )
    if meta.id and meta.id != node_dir.name:
        warnings.append(
            CatalogWarning(
                ref=ref,
                file="meta.yaml",
                code="id_mismatch",
                message=f"meta id {meta.id!r} 与目录名 {node_dir.name!r} 不一致",
            )
        )
    if classification.clothing and meta.clothing_state and classification.clothing != meta.clothing_state:
        warnings.append(
            CatalogWarning(
                ref=ref,
                file="meta.yaml",
                code="meta_classify_mismatch",
                message="classify.clothing 与 meta.clothing.state 不一致",
                details={
                    "classify": classification.clothing,
                    "meta": meta.clothing_state,
                },
            )
        )
    if not meta.positive_terms:
        warnings.append(
            CatalogWarning(
                ref=ref,
                file="meta.yaml",
                code="empty_action_prompt",
                message="动作节点没有可用的 tags.action",
            )
        )

    content_hash = stable_json_hash(
        {
            name: {"exists": file_exists[name], "hash": file_hashes[name]}
            for name in NODE_FILENAMES
        }
    )
    negative_hash = stable_json_hash(meta.negative_raw)
    item = ActionCatalogItem(
        ref=ref,
        id=meta.id or node_dir.name,
        source=CatalogSource(
            root_id=root_id,
            relative_path=ref,
            group=ref.split("/", 1)[0],
        ),
        files=CatalogFiles(
            tags_path=f"{ref}/tags.txt" if file_exists["tags.txt"] else None,
            classify_path=f"{ref}/classify.yaml" if file_exists["classify.yaml"] else None,
            meta_path=f"{ref}/meta.yaml" if file_exists["meta.yaml"] else None,
            tags_hash=file_hashes["tags.txt"],
            classify_hash=file_hashes["classify.yaml"],
            meta_hash=file_hashes["meta.yaml"],
            content_hash=content_hash,
        ),
        classification=classification,
        action=CatalogActionSummary(
            name=meta.name or meta.id or node_dir.name,
            description=meta.description,
            character_scope=meta.character_scope,
            positive_terms=meta.positive_terms,
            negative_terms_count=len(meta.negative_terms),
            negative_hash=negative_hash,
        ),
        alias_group=content_hash,
        canonical_ref=ref,
        aliases=[ref],
    )
    return item, warnings


def _load_yaml(
    content: bytes | None,
    ref: str,
    filename: str,
    warnings: list[CatalogWarning],
) -> object:
    if content is None:
        return None
    try:
        text = content.decode("utf-8")
        return yaml.safe_load(text)
    except (UnicodeError, yaml.YAMLError) as exc:
        warnings.append(
            CatalogWarning(
                ref=ref,
                file=filename,
                code="parse_error",
                message=f"解析 {filename} 失败: {exc}",
            )
        )
        return None


def _apply_aliases(
    items: list[ActionCatalogItem],
    warnings: dict[str, list[CatalogWarning]],
) -> None:
    groups: dict[str, list[ActionCatalogItem]] = defaultdict(list)
    for item in items:
        groups[item.files.content_hash].append(item)
    for content_hash, group_items in groups.items():
        aliases = sorted(item.ref for item in group_items)
        canonical_ref = aliases[0]
        for item in group_items:
            item.alias_group = content_hash
            item.canonical_ref = canonical_ref
            item.aliases = aliases
            if len(aliases) > 1:
                warnings[item.ref].append(
                    CatalogWarning(
                        ref=item.ref,
                        code="duplicate_content",
                        message=f"节点内容与 {canonical_ref} 完全相同",
                        details={"canonical_ref": canonical_ref, "aliases": aliases},
                    )
                )


def _detect_duplicate_prompts(
    items: list[ActionCatalogItem],
    warnings: dict[str, list[CatalogWarning]],
) -> None:
    prompt_groups: dict[str, list[ActionCatalogItem]] = defaultdict(list)
    for item in items:
        if item.action.positive_terms:
            prompt_groups[stable_json_hash(item.action.positive_terms)].append(item)
    for group_items in prompt_groups.values():
        classification_hashes = {
            stable_json_hash(item.classification.model_dump(mode="json")) for item in group_items
        }
        if len(group_items) < 2 or len(classification_hashes) < 2:
            continue
        refs = sorted(item.ref for item in group_items)
        for item in group_items:
            warnings[item.ref].append(
                CatalogWarning(
                    ref=item.ref,
                    file="meta.yaml",
                    code="duplicate_content",
                    message="动作 prompt 相同但分类不同",
                    details={"refs": refs},
                )
            )


def _dedupe_preserve(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
