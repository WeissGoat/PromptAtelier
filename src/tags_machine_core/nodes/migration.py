from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

NEGATIVE_EXTENSION_KEYS = {
    "origin_uc",
    "uc",
    "negative_prompt",
    "after_uc",
    "after_negative_prompt",
}

LEGACY_PROMPT_DIRECTIVE_KEYS = {
    "type",
}

LEGACY_INLINE_EXTENSION_MARKERS = (
    "after_uc",
    "origin_uc",
    "origin_clear",
    "gen_json",
    "gen_param",
)

MIGRATION_OUTPUT_DIRS = {
    "artist": "artists",
    "character": "characters",
    "action": "actions",
    "background": "backgrounds",
}

MIGRATION_OUTPUT_FILES = {
    "artist": "node.yaml",
    "character": "meta.yaml",
    "action": "meta.yaml",
    "background": "meta.yaml",
}


def audit_legacy_tags(source: str | Path, *, kind: str) -> dict[str, Any]:
    """扫描旧 tags.txt 并生成迁移预检报告；只读源目录，不写旧项目。"""
    migrators = {
        "artist": migrate_legacy_artist_tags,
        "character": migrate_legacy_character_tags,
        "action": migrate_legacy_action_tags,
        "background": migrate_legacy_background_tags,
    }
    if kind not in migrators:
        raise ValueError(f"Unsupported legacy tag kind: {kind}")

    source_path = Path(source)
    tags_paths = _collect_legacy_tags_paths(source_path)
    items: list[dict[str, Any]] = []
    issue_counts: dict[str, int] = {}

    for tags_path in tags_paths:
        try:
            node = migrators[kind](tags_path)
            item = _audit_migrated_node(node, kind=kind, tags_path=tags_path)
        except Exception as exc:  # pragma: no cover - 具体错误形态由被审计文件决定
            item = {
                "source_file": str(tags_path),
                "source_dir": str(tags_path.parent),
                "kind": kind,
                "status": "error",
                "issues": [
                    {
                        "code": "migration_error",
                        "severity": "error",
                        "message": str(exc),
                    }
                ],
            }
        items.append(item)
        for issue in item.get("issues", []):
            code = str(issue.get("code") or "unknown")
            issue_counts[code] = issue_counts.get(code, 0) + 1

    summary = {
        "total": len(items),
        "ok": sum(1 for item in items if item["status"] == "ok"),
        "needs_review": sum(1 for item in items if item["status"] == "needs_review"),
        "errors": sum(1 for item in items if item["status"] == "error"),
        "issue_counts": dict(sorted(issue_counts.items())),
    }
    return {
        "schema": "tags-machine-core.legacy-tags-audit/v1",
        "kind": kind,
        "source": str(source_path),
        "summary": summary,
        "items": items,
    }


def plan_legacy_tags_migration(
    source: str | Path,
    *,
    kind: str,
    output_root: str | Path,
) -> dict[str, Any]:
    """生成旧 tags.txt 批量迁移计划；只输出计划，不写节点 YAML。"""
    if kind not in MIGRATION_OUTPUT_DIRS:
        raise ValueError(f"Unsupported legacy tag kind: {kind}")

    audit = audit_legacy_tags(source, kind=kind)
    output_root_path = Path(output_root)
    items: list[dict[str, Any]] = []
    target_counts: dict[str, int] = {}

    for audit_item in audit["items"]:
        node_id = str(audit_item.get("node_id") or Path(audit_item["source_dir"]).name)
        target_dir_name = _safe_migration_node_dir_name(node_id)
        target_file = (
            output_root_path
            / "nodes"
            / MIGRATION_OUTPUT_DIRS[kind]
            / target_dir_name
            / MIGRATION_OUTPUT_FILES[kind]
        )
        target_file_text = str(target_file)
        target_counts[target_file_text] = target_counts.get(target_file_text, 0) + 1
        issues = [dict(issue) for issue in audit_item.get("issues", [])]
        target_exists = target_file.exists()
        if target_exists:
            _append_issue(
                issues,
                "target_file_exists",
                "review",
                "目标节点文件已经存在；批量写入前需要决定跳过或显式覆盖。",
            )

        items.append(
            {
                "source_file": audit_item["source_file"],
                "source_dir": audit_item["source_dir"],
                "kind": kind,
                "node_id": node_id,
                "safe_node_dir": target_dir_name,
                "target_dir": str(target_file.parent),
                "target_file": target_file_text,
                "target_exists": target_exists,
                "audit_status": audit_item["status"],
                "migration_status": _migration_status(audit_item["status"], target_exists, issues),
                "issues": issues,
            }
        )

    for item in items:
        if target_counts[item["target_file"]] <= 1:
            continue
        _append_issue(
            item["issues"],
            "target_path_collision",
            "error",
            "多个旧节点会写入同一个目标路径；需要人工调整节点 id 或输出路径。",
        )
        item["migration_status"] = "blocked"

    return {
        "schema": "tags-machine-core.legacy-tags-migration-plan/v1",
        "kind": kind,
        "source": str(Path(source)),
        "output_root": str(output_root_path),
        "summary": _migration_plan_summary(items),
        "audit_summary": audit["summary"],
        "items": items,
    }


def apply_legacy_tags_migration(
    source: str | Path,
    *,
    kind: str,
    output_root: str | Path,
) -> dict[str, Any]:
    """按迁移计划写出 ready 节点；不覆盖目标文件，也不写旧源目录。"""
    plan = plan_legacy_tags_migration(source, kind=kind, output_root=output_root)
    migrator = _legacy_migrator(kind)
    items: list[dict[str, Any]] = []

    for plan_item in plan["items"]:
        target_file = Path(plan_item["target_file"])
        item: dict[str, Any] = {
            "source_file": plan_item["source_file"],
            "source_dir": plan_item["source_dir"],
            "target_file": str(target_file),
            "migration_status": plan_item["migration_status"],
        }
        if plan_item["migration_status"] != "ready":
            item["result"] = "skipped"
            item["reason"] = f"migration_status:{plan_item['migration_status']}"
            items.append(item)
            continue
        if target_file.exists():
            item["result"] = "skipped"
            item["reason"] = "target_exists"
            items.append(item)
            continue

        try:
            node = migrator(plan_item["source_file"])
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(
                yaml.safe_dump(node, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover - 具体文件错误由环境决定
            item["result"] = "error"
            item["error"] = str(exc)
        else:
            item["result"] = "written"
        items.append(item)

    return {
        "schema": "tags-machine-core.legacy-tags-migration-apply/v1",
        "kind": kind,
        "source": str(Path(source)),
        "output_root": str(Path(output_root)),
        "plan_summary": plan["summary"],
        "summary": _apply_migration_summary(items),
        "items": items,
    }


def migrate_legacy_artist_tags(
    source: str | Path,
    *,
    node_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """把旧画风 tags.txt 转成结构化 artist node，不依赖旧项目运行时代码。"""
    tags_path = _resolve_tags_path(source)
    artist_dir = tags_path.parent
    prompt_lines, ext_lines = _split_legacy_tags_lines(tags_path)
    prompt_lines, type_flags = _extract_legacy_type_flags(prompt_lines)
    cleaned_prompt_lines = [line.strip(" ,") for line in prompt_lines]
    cleaned_prompt_lines = [line for line in cleaned_prompt_lines if line]
    prompt_prefix, prompt_suffix = _legacy_formula_prompt_parts(prompt_lines)

    novelai: dict[str, Any] = {
        "legacy_compat": True,
        "include_common_tags": False,
        "prompt_prefix": prompt_prefix,
        "prompt_suffix": prompt_suffix,
        "params": {},
    }
    flags: list[str] = list(type_flags)
    legacy_extensions: dict[str, str] = {}

    gen_json_seen = False
    for line in ext_lines:
        key, value = _split_ext_line(line)
        if not key:
            continue
        if key in {"origin_uc", "uc"}:
            if value:
                novelai["negative_prompt"] = [value]
        elif key == "after_uc":
            if value:
                novelai["after_negative_prompt"] = [value]
        elif key == "gen_json":
            if not gen_json_seen:
                novelai["params"].update(_parse_json_value(value, tags_path))
                gen_json_seen = True
        elif key in {"not_quailty_prompts", "not_quality_prompts"}:
            flags.append(key)
        else:
            flags.append(key)
            if value:
                legacy_extensions[key] = value

    if flags:
        novelai["flags"] = sorted(set(flags))
    if legacy_extensions:
        novelai["legacy_extensions"] = legacy_extensions

    return {
        "schema": "tags-machine.artist/v1",
        "kind": "artist",
        "id": node_id or artist_dir.name,
        "name": name or artist_dir.name,
        "description": "由旧画风 tags.txt 迁移生成。请人工复核 tags 分组和跨后端配置。",
        "tags": {"artist": cleaned_prompt_lines},
        "negative_prompt": [],
        "renderers": {"novelai": novelai},
        "legacy": {
            "source_file": str(tags_path),
            "raw_lines": prompt_lines + (["="] if ext_lines else []) + ext_lines,
            "raw_sections": {
                "prompt": prompt_lines,
                "extension": ext_lines,
            },
        },
        "agent": {
            "summary": "从旧 tags.txt 自动迁移的画风节点，后端行为优先保持 NovelAI 兼容。",
            "labels": ["artist", "migrated", "legacy_tags_txt"],
        },
    }


def migrate_legacy_character_tags(
    source: str | Path,
    *,
    node_id: str | None = None,
    name: str | None = None,
    character_id: str | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    """把旧角色 tags.txt 转成结构化 character meta，旧替换规则只归档不执行。"""
    tags_path = _resolve_tags_path(source)
    character_dir = tags_path.parent
    prompt_lines, ext_lines = _split_legacy_tags_lines(tags_path)
    raw_prompt_lines = list(prompt_lines)
    type_lines = [line for line in raw_prompt_lines if line[:4] == "type"]
    prompt_lines, _type_flags = _extract_legacy_type_flags(prompt_lines)
    prompt_tags_by_line = [_split_top_level_commas(line) for line in prompt_lines]
    identity_tags = prompt_tags_by_line[0] if prompt_tags_by_line else []
    tags: dict[str, list[str]] = {}

    if identity_tags:
        tags["character"] = identity_tags[:1]
    if len(identity_tags) > 1:
        tags["copyright"] = identity_tags[1:]

    for line_tags in prompt_tags_by_line[1:]:
        for tag in line_tags:
            section = _classify_legacy_character_tag(tag)
            tags.setdefault(section, []).append(tag)

    result: dict[str, Any] = {
        "schema": "tags-machine.character/v1",
        "kind": "character",
        "id": node_id or character_dir.name,
        "name": name or character_dir.name,
        "character_id": character_id or (identity_tags[0] if identity_tags else character_dir.name),
        "description": "由旧角色 tags.txt 迁移生成。请人工复核 tags 分组；旧替换规则只保留在 legacy。",
        "tags": tags,
        "negative_prompt": _collect_legacy_negative_prompt(ext_lines),
        "legacy": {
            "source_file": str(tags_path),
            "raw_lines": raw_prompt_lines + (["="] if ext_lines else []) + ext_lines,
            "raw_sections": {
                "prompt": prompt_lines,
                "extension": ext_lines,
                **({"type": type_lines} if type_lines else {}),
            },
        },
        "agent": {
            "summary": "从旧 tags.txt 自动迁移的角色节点，只包含角色素材事实；旧替换规则没有提升为 v1 规则字段。",
            "labels": ["character", "migrated", "legacy_tags_txt", "needs_review"],
        },
    }
    if variant:
        result["variant"] = variant
    return result


def migrate_legacy_action_tags(
    source: str | Path,
    *,
    node_id: str | None = None,
    name: str | None = None,
    character_scope: str | None = None,
) -> dict[str, Any]:
    """把旧动作 tags.txt 转成结构化 action meta，不把规则写进节点。"""
    tags_path = _resolve_tags_path(source)
    action_dir = tags_path.parent
    prompt_lines, ext_lines = _split_legacy_tags_lines(tags_path)
    raw_prompt_lines = list(prompt_lines)
    type_lines = [line for line in raw_prompt_lines if line[:4] == "type"]
    prompt_lines, _type_flags = _extract_legacy_type_flags(prompt_lines)
    action_tags = _split_legacy_prompt_tags(prompt_lines)
    resolved_scope = character_scope or _infer_action_character_scope(action_tags, tags_path)
    scope_source = "override" if character_scope else "inferred"

    return {
        "schema": "tags-machine.action/v1",
        "kind": "action",
        "id": node_id or action_dir.name,
        "name": name or action_dir.name,
        "description": "由旧动作 tags.txt 迁移生成。旧动作常混有角色、背景或画风词，请人工复核。",
        "tags": {"action": action_tags},
        "negative_prompt": _collect_legacy_negative_prompt(ext_lines),
        "character_scope": resolved_scope,
        "legacy": {
            "source_file": str(tags_path),
            "raw_lines": raw_prompt_lines + (["="] if ext_lines else []) + ext_lines,
            "raw_sections": {
                "prompt": prompt_lines,
                **({"type": type_lines} if type_lines else {}),
                "extension": ext_lines,
            },
        },
        "agent": {
            "summary": f"从旧 tags.txt 自动迁移的动作节点，character_scope={resolved_scope}（{scope_source}）。",
            "labels": [
                "action",
                "migrated",
                "legacy_tags_txt",
                "needs_review",
                resolved_scope,
                f"character_scope_{scope_source}",
            ],
        },
    }


def migrate_legacy_background_tags(
    source: str | Path,
    *,
    node_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """把旧背景 tags.txt 转成结构化 background meta，不依赖旧项目运行时代码。"""
    tags_path = _resolve_tags_path(source)
    background_dir = tags_path.parent
    prompt_lines, ext_lines = _split_legacy_tags_lines(tags_path)
    cleaned_prompt_lines = [line.strip(" ,") for line in prompt_lines]
    cleaned_prompt_lines = [line for line in cleaned_prompt_lines if line]

    negative_prompt: list[str] = []
    for line in ext_lines:
        key, value = _split_ext_line(line)
        if key in NEGATIVE_EXTENSION_KEYS and value:
            negative_prompt.append(value)

    return {
        "schema": "tags-machine.background/v1",
        "kind": "background",
        "id": node_id or background_dir.name,
        "name": name or background_dir.name,
        "description": "由旧背景 tags.txt 迁移生成。请人工复核 tags 分组。",
        "tags": {"background": cleaned_prompt_lines},
        "negative_prompt": negative_prompt,
        "legacy": {
            "source_file": str(tags_path),
            "raw_lines": prompt_lines + (["="] if ext_lines else []) + ext_lines,
            "raw_sections": {
                "prompt": prompt_lines,
                "extension": ext_lines,
            },
        },
        "agent": {
            "summary": "从旧 tags.txt 自动迁移的背景节点，只包含场景素材和背景级负向词。",
            "labels": ["background", "migrated", "legacy_tags_txt"],
        },
    }


def _resolve_tags_path(source: str | Path) -> Path:
    path = Path(source)
    if path.is_dir():
        path = path / "tags.txt"
    if not path.exists():
        raise FileNotFoundError(f"Legacy tags.txt not found: {path}")
    if path.name.lower() != "tags.txt":
        raise ValueError(f"Expected a tags.txt file or directory containing tags.txt: {path}")
    return path


def _collect_legacy_tags_paths(source: Path) -> list[Path]:
    if source.is_file():
        return [_resolve_tags_path(source)]
    if not source.exists():
        raise FileNotFoundError(f"Legacy tags source not found: {source}")
    direct_tags = source / "tags.txt"
    if direct_tags.exists():
        return [direct_tags]
    return sorted(path for path in source.rglob("tags.txt") if path.is_file())


def _legacy_migrator(kind: str):
    migrators = {
        "artist": migrate_legacy_artist_tags,
        "character": migrate_legacy_character_tags,
        "action": migrate_legacy_action_tags,
        "background": migrate_legacy_background_tags,
    }
    if kind not in migrators:
        raise ValueError(f"Unsupported legacy tag kind: {kind}")
    return migrators[kind]


def _safe_migration_node_dir_name(node_id: str) -> str:
    value = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in node_id)
    value = value.strip().rstrip(".")
    if not value or value in {".", ".."}:
        return "unnamed"
    return value


def _migration_status(audit_status: str, target_exists: bool, issues: list[dict[str, Any]]) -> str:
    if audit_status == "error":
        return "error"
    if target_exists:
        return "target_exists"
    if any(issue.get("severity") == "error" for issue in issues):
        return "blocked"
    if audit_status == "needs_review":
        return "needs_review"
    return "ready"


def _migration_plan_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("migration_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        for issue in item.get("issues", []):
            code = str(issue.get("code") or "unknown")
            issue_counts[code] = issue_counts.get(code, 0) + 1
    return {
        "total": len(items),
        "ready": status_counts.get("ready", 0),
        "needs_review": status_counts.get("needs_review", 0),
        "target_exists": status_counts.get("target_exists", 0),
        "blocked": status_counts.get("blocked", 0),
        "errors": status_counts.get("error", 0),
        "status_counts": dict(sorted(status_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
    }


def _apply_migration_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    result_counts: dict[str, int] = {}
    skip_reasons: dict[str, int] = {}
    for item in items:
        result = str(item.get("result") or "unknown")
        result_counts[result] = result_counts.get(result, 0) + 1
        if result == "skipped":
            reason = str(item.get("reason") or "unknown")
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    return {
        "total": len(items),
        "written": result_counts.get("written", 0),
        "skipped": result_counts.get("skipped", 0),
        "errors": result_counts.get("error", 0),
        "result_counts": dict(sorted(result_counts.items())),
        "skip_reasons": dict(sorted(skip_reasons.items())),
    }


def _audit_migrated_node(node: dict[str, Any], *, kind: str, tags_path: Path) -> dict[str, Any]:
    tags = node.get("tags") if isinstance(node.get("tags"), dict) else {}
    issues: list[dict[str, Any]] = []
    extension_keys = _legacy_extension_keys(node)

    if kind == "artist":
        _audit_artist_node(node, tags, extension_keys, issues)
    elif kind == "character":
        _audit_character_node(node, tags, extension_keys, issues)
    elif kind == "action":
        _audit_action_node(node, tags, extension_keys, issues)
    elif kind == "background":
        _audit_background_node(node, tags, extension_keys, issues)

    needs_review = any(issue.get("severity") != "info" for issue in issues)
    item: dict[str, Any] = {
        "source_file": str(tags_path),
        "source_dir": str(tags_path.parent),
        "kind": kind,
        "status": "needs_review" if needs_review else "ok",
        "node_id": node.get("id"),
        "name": node.get("name"),
        "schema": node.get("schema"),
        "tag_counts_by_section": {
            str(section): len(values) for section, values in sorted(tags.items())
        },
        "negative_prompt_count": len(node.get("negative_prompt") or []),
        "extension_keys": extension_keys,
        "issues": issues,
    }
    if kind == "action":
        item["character_scope"] = node.get("character_scope")
        item["character_scope_source"] = _action_scope_source(node)
    if kind == "character":
        item["character_id"] = node.get("character_id")
        if node.get("variant"):
            item["variant"] = node.get("variant")
    return item


def _audit_artist_node(
    node: dict[str, Any],
    tags: dict[str, list[str]],
    extension_keys: list[str],
    issues: list[dict[str, Any]],
) -> None:
    if not tags.get("artist"):
        _append_issue(issues, "empty_artist_tags", "review", "artist 节点没有可迁移的正向 tags。")
    known_keys = {
        "origin_uc",
        "uc",
        "after_uc",
        "gen_json",
        "not_quailty_prompts",
        "not_quality_prompts",
    }
    unknown_keys = [key for key in extension_keys if key not in known_keys]
    if unknown_keys:
        _append_issue(
            issues,
            "artist_unknown_legacy_extension",
            "review",
            "artist 节点包含未提升为结构化字段的旧扩展，需要确认是否仍要保留。",
            samples=unknown_keys,
            count=len(unknown_keys),
        )
    params = ((node.get("renderers") or {}).get("novelai") or {}).get("params") or {}
    reference_keys = [
        key
        for key in (
            "reference_image_multiple",
            "reference_strength_multiple",
            "reference_information_extracted_multiple",
            "director_reference_images",
        )
        if key in params
    ]
    if reference_keys:
        _append_issue(
            issues,
            "artist_reference_params_present",
            "info",
            "artist 节点包含 NovelAI reference/vibe 参数，迁移后验收需要覆盖这些数组字段。",
            samples=reference_keys,
            count=len(reference_keys),
        )


def _audit_character_node(
    node: dict[str, Any],
    tags: dict[str, list[str]],
    extension_keys: list[str],
    issues: list[dict[str, Any]],
) -> None:
    if not tags.get("character"):
        _append_issue(issues, "missing_character_identity", "review", "角色节点缺少 character 身份 tag。")
    unclassified = list(tags.get("unclassified") or [])
    if unclassified:
        _append_issue(
            issues,
            "character_unclassified_tags",
            "review",
            "角色 tags 中存在无法自动分类的条目，需要人工确认 section。",
            samples=unclassified[:10],
            count=len(unclassified),
        )
    archived_keys = [key for key in extension_keys if key not in NEGATIVE_EXTENSION_KEYS]
    if archived_keys:
        _append_issue(
            issues,
            "character_legacy_extension_archived",
            "review",
            "旧角色替换/扩展规则只归档到 legacy，不会在 v1 节点中执行。",
            samples=archived_keys,
            count=len(archived_keys),
        )


def _audit_action_node(
    node: dict[str, Any],
    tags: dict[str, list[str]],
    extension_keys: list[str],
    issues: list[dict[str, Any]],
) -> None:
    action_tags = list(tags.get("action") or [])
    if not action_tags:
        _append_issue(issues, "empty_action_tags", "review", "动作节点没有可迁移的动作 tags。")
    if node.get("character_scope") == "default" and _action_scope_source(node) == "inferred":
        _append_issue(
            issues,
            "action_default_scope_needs_review",
            "review",
            "动作节点只能推断为 default，局部镜头需要人工补 character_scope。",
        )
    mixed_tags = _probable_character_tags_in_action(action_tags)
    if mixed_tags:
        _append_issue(
            issues,
            "action_maybe_contains_character_tags",
            "review",
            "动作 tags 疑似混入角色外观词，迁移后建议拆回 character 节点或交给 agent 重组。",
            samples=mixed_tags[:10],
            count=len(mixed_tags),
        )
    archived_keys = [key for key in extension_keys if key not in NEGATIVE_EXTENSION_KEYS]
    if archived_keys:
        _append_issue(
            issues,
            "action_legacy_extension_archived",
            "review",
            "旧动作扩展只归档到 legacy，不会作为 v1 规则或后端参数执行。",
            samples=archived_keys,
            count=len(archived_keys),
        )


def _audit_background_node(
    node: dict[str, Any],
    tags: dict[str, list[str]],
    extension_keys: list[str],
    issues: list[dict[str, Any]],
) -> None:
    if not tags.get("background"):
        _append_issue(issues, "empty_background_tags", "review", "背景节点没有可迁移的场景 tags。")
    ignored_keys = [key for key in extension_keys if key not in NEGATIVE_EXTENSION_KEYS]
    if ignored_keys:
        _append_issue(
            issues,
            "background_legacy_extension_ignored",
            "review",
            "背景迁移不会提升旧后端扩展参数，需要确认是否应移到 artist 或 renderer adapter。",
            samples=ignored_keys,
            count=len(ignored_keys),
        )


def _legacy_extension_keys(node: dict[str, Any]) -> list[str]:
    legacy = node.get("legacy") if isinstance(node.get("legacy"), dict) else {}
    raw_sections = legacy.get("raw_sections") if isinstance(legacy.get("raw_sections"), dict) else {}
    ext_lines = raw_sections.get("extension") if isinstance(raw_sections.get("extension"), list) else []
    keys: set[str] = set()
    for line in ext_lines:
        key, _ = _split_ext_line(str(line))
        if key:
            keys.add(key)
    return sorted(keys)


def _action_scope_source(node: dict[str, Any]) -> str:
    labels = ((node.get("agent") or {}).get("labels") or [])
    for label in labels:
        value = str(label)
        if value.startswith("character_scope_"):
            return value.removeprefix("character_scope_")
    return "unknown"


def _probable_character_tags_in_action(action_tags: list[str]) -> list[str]:
    character_sections = {
        "hair",
        "eyes",
        "face",
        "headwear",
        "ears",
        "tail",
        "wings",
        "hands",
        "legwear",
        "feet",
        "upper_clothes",
        "lower_clothes",
        "full_body_clothes",
        "accessories",
        "weapons",
        "props",
    }
    return [
        tag
        for tag in action_tags
        if _classify_legacy_character_tag(tag) in character_sections
    ]


def _append_issue(
    issues: list[dict[str, Any]],
    code: str,
    severity: str,
    message: str,
    *,
    samples: list[str] | None = None,
    count: int | None = None,
) -> None:
    issue: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if count is not None:
        issue["count"] = count
    if samples:
        issue["samples"] = samples
    issues.append(issue)


def _split_legacy_tags_lines(path: Path) -> tuple[list[str], list[str]]:
    raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    lines = [line.strip() for line in raw_lines if line.strip()]
    prompt_lines: list[str] = []
    ext_lines: list[str] = []
    in_ext = False
    for line in lines:
        if in_ext:
            ext_lines.append(line)
            continue
        stripped = line.strip()
        if stripped.startswith("="):
            in_ext = True
            inline_ext = stripped[1:].strip(" ,")
            if inline_ext:
                ext_lines.append(inline_ext)
            continue
        if any(marker in line for marker in LEGACY_INLINE_EXTENSION_MARKERS):
            in_ext = True
            ext_lines.append(line)
            continue
        prompt_lines.append(line)
    return prompt_lines, ext_lines


def _extract_legacy_type_flags(prompt_lines: list[str]) -> tuple[list[str], list[str]]:
    cleaned_lines: list[str] = []
    flags: list[str] = []
    for line in prompt_lines:
        if line[:4] == "type":
            flags.extend(part.strip() for part in line.split(",")[1:] if part.strip())
        else:
            cleaned_lines.append(line)
    return cleaned_lines, flags


def _legacy_formula_prompt_parts(prompt_lines: list[str]) -> tuple[list[str], list[str]]:
    if not prompt_lines:
        return [], []
    prefix = [line.strip(" ,") for line in prompt_lines[:2]]
    suffix = [line.strip(" ,") for line in prompt_lines[2:]]
    return [line for line in prefix if line], [line for line in suffix if line]


def _split_ext_line(line: str) -> tuple[str, str]:
    if "," not in line:
        return line.strip(), ""
    key, value = line.split(",", 1)
    return key.strip(), value.strip()


def _collect_legacy_negative_prompt(ext_lines: list[str]) -> list[str]:
    negative_prompt: list[str] = []
    for line in ext_lines:
        key, value = _split_ext_line(line)
        if key in NEGATIVE_EXTENSION_KEYS and value:
            negative_prompt.append(value)
    return negative_prompt


def _split_legacy_prompt_tags(prompt_lines: list[str]) -> list[str]:
    tags: list[str] = []
    for line in prompt_lines:
        key, _ = _split_ext_line(line)
        if key in LEGACY_PROMPT_DIRECTIVE_KEYS:
            continue
        tags.extend(_split_top_level_commas(line))
    return tags


def _split_top_level_commas(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    stack: list[str] = []
    closing_to_opening = {")": "(", "]": "[", "}": "{"}
    for char in text:
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if stack and stack[-1] == closing_to_opening[char]:
                stack.pop()
        if char == "," and not stack:
            item = "".join(current).strip(" ,")
            if item:
                items.append(item)
            current = []
            continue
        current.append(char)
    item = "".join(current).strip(" ,")
    if item:
        items.append(item)
    return items


def _infer_action_character_scope(action_tags: list[str], source: Path) -> str:
    text = " ".join([*action_tags, *source.parts]).lower().replace("_", " ")

    def has_any(phrases: tuple[str, ...]) -> bool:
        return any(phrase in text for phrase in phrases)

    if has_any(
        (
            "foot focus",
            "feet focus",
            "toes focus",
            "foot close-up",
            "feet close-up",
            "shoes close-up",
            "soles",
            "sole ",
            "toes",
            "toenails",
            "foot in view",
            "st ft",
        )
    ):
        return "foot_detail"
    if has_any(
        (
            "hand focus",
            "hands focus",
            "hand close-up",
            "hands close-up",
            "close-up hands",
            "pov hands",
            "finger focus",
        )
    ):
        return "hand_detail"
    if has_any(
        (
            "face focus",
            "close-up face",
            "face close-up",
            "eye focus",
            "eyes focus",
            "mouth focus",
        )
    ):
        return "face_detail"
    if has_any(("portrait",)):
        return "portrait"
    if has_any(("upper body",)):
        return "upper_body"
    if has_any(("lower body", "thighs focus", "ass focus", "legs focus", "upper thigh")):
        return "lower_body"
    if has_any(("full body",)):
        return "full_body"
    return "default"


def _classify_legacy_character_tag(tag: str) -> str:
    normalized = tag.lower().strip().replace(" ", "_")
    if any(marker in normalized for marker in ("_hair", "hair_", "hairclip", "hairband", "ahoge")):
        if any(marker in normalized for marker in ("hairclip", "hairband", "hair_ornament", "hair_bow")):
            return "headwear"
        return "hair"
    if "_eyes" in normalized or normalized.endswith("_eye") or normalized in {"heterochromia"}:
        return "eyes"
    if any(marker in normalized for marker in ("mouth", "smile", "fang", "scar_across_eye", "mask")):
        return "face"
    if any(
        marker in normalized
        for marker in (
            "hat",
            "ribbon",
            "halo",
            "horn",
            "headdress",
            "headband",
            "hair_ornament",
            "hairclip",
            "hair_bow",
            "crown",
            "headphones",
            "headset",
            "earphones",
            "goggles",
            "eyewear",
            "veil",
        )
    ):
        return "headwear"
    if "ear" in normalized:
        return "ears"
    if "tail" in normalized:
        return "tail"
    if "wing" in normalized:
        return "wings"
    if (
        normalized in {"ring", "rings", "multiple_rings"}
        or any(marker in normalized for marker in ("bracelet", "watch", "hand_jewel", "hand_ornament"))
    ):
        return "hands"
    if any(
        marker in normalized
        for marker in (
            "glove",
            "mitten",
            "handwear",
            "armband",
            "armlet",
            "arm_belt",
            "arm_warmer",
            "sleeve",
            "gauntlet",
        )
    ):
        return "hands"
    if any(
        marker in normalized
        for marker in (
            "thighhigh",
            "pantyhose",
            "socks",
            "kneehigh",
            "legwear",
            "stocking",
            "garter",
            "thigh_strap",
        )
    ):
        return "legwear"
    if any(
        marker in normalized
        for marker in (
            "shoe",
            "boot",
            "sneaker",
            "loafers",
            "high_heels",
            "mary_janes",
            "footwear",
            "sandal",
            "anklet",
        )
    ):
        return "feet"
    if any(marker in normalized for marker in ("barefoot", "bare_feet", "feet", "toe", "soles")):
        return "feet"
    if any(marker in normalized for marker in ("sword", "gun", "shield", "weapon", "shirasaya", "wand")):
        return "weapons"
    if any(marker in normalized for marker in ("plush", "bag", "book", "umbrella", "instrument")):
        return "props"
    if any(
        marker in normalized
        for marker in (
            "dress",
            "kimono",
            "school_uniform",
            "uniform",
            "serafuku",
        )
    ):
        return "full_body_clothes"
    if any(marker in normalized for marker in ("skirt", "pants", "shorts", "bloomers")):
        return "lower_clothes"
    if any(
        marker in normalized
        for marker in (
            "blazer",
            "jacket",
            "shirt",
            "coat",
            "sweater",
            "hoodie",
            "sailor",
            "collar",
            "sleeves",
            "armor",
            "bra",
        )
    ):
        return "upper_clothes"
    if any(
        marker in normalized
        for marker in (
            "breasts",
            "skin",
            "navel",
            "body",
            "thighs",
            "third_eye",
            "eyeball",
            "heart_out_of_chest",
        )
    ):
        return "body"
    if any(marker in normalized for marker in ("necklace", "choker", "belt", "logo", "badge")):
        return "accessories"
    return "unclassified"


def _parse_json_value(value: str, source: Path) -> dict[str, Any]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid gen_json in {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"gen_json must be a JSON object in {source}")
    return data
