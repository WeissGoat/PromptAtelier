from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..action_resolution import ActionNodeValueResolver
from ..catalog.repository import CatalogRepository
from ..config import load_workspace
from ..logging import get_logger
from ..models import AssetRecord, ImageNodeRef
from ..identity import DEFAULT_NODE_IDENTITY_NORMALIZER
from ..tasks.paths import TaskPaths
from ..tasks.repository import TaskRepository
from ..tasks.scanner import CurrentSelectionScanner
from .models import InlineContent
from .paths import PlanPaths
from .repository import PlanRepository


logger = get_logger(__name__)

FACET_FIELDS = (
    "phase",
    "species",
    "cast",
    "domain",
    "subtype",
    "pose",
    "environment",
    "tone",
    "flags",
    "clothing",
)
NODE_FIELDS = ("artist", "character", "action_group", "action", "background")


class AssetSearchFilter(BaseModel):
    import_id: str | None = None
    text: str = ""
    artist: str | None = None
    character: str | None = None
    action_group: str | None = None
    action: str | None = None
    facets: dict[str, set[str]] = Field(default_factory=dict)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)

    @field_validator("import_id", "text", "artist", "character", "action_group", "action")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("facets")
    @classmethod
    def normalize_facets(cls, value: dict[str, set[str]]) -> dict[str, set[str]]:
        normalized: dict[str, set[str]] = {}
        for field, values in value.items():
            field_name = str(field).strip()
            if field_name not in FACET_FIELDS:
                raise ValueError(f"不支持的 classify facet：{field_name}")
            normalized[field_name] = {
                str(item).strip() for item in values if str(item).strip()
            }
        return normalized


class AssetSearchResult(BaseModel):
    asset_id: str
    path: str
    display_name: str
    width: int
    height: int
    image_format: str
    values: dict[str, list[str]]
    facets: dict[str, list[str]]
    warnings: list[str] = Field(default_factory=list)
    usage: list[str] = Field(default_factory=list)


class AssetPageResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.asset-page/v1"] = Field(
        default="publishing-workspace.asset-page/v1",
        alias="schema",
    )
    items: list[AssetSearchResult]
    offset: int
    limit: int
    has_more: bool
    next_offset: int | None


class NodeOption(BaseModel):
    role: str
    name: str
    ref: str | None = None
    relative: str | None = None


class NodeListResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.web.node-list/v1"] = Field(
        default="publishing-workspace.web.node-list/v1",
        alias="schema",
    )
    role: str
    nodes: list[NodeOption]
    offset: int
    limit: int
    has_more: bool


class ClassifyFacetReader:
    """从 action 节点目录附近的 classify.yaml 读取检索字段。"""

    def __init__(self) -> None:
        self._path_cache: dict[str, Path | None] = {}
        self._yaml_cache: dict[Path, tuple[int, dict[str, Any]]] = {}
        self._asset_cache: dict[str, tuple[dict[str, list[str]], list[str]]] = {}

    def read(self, asset: AssetRecord) -> tuple[dict[str, list[str]], list[str]]:
        cached = self._asset_cache.get(asset.asset_id)
        if cached is not None:
            return cached

        values: dict[str, list[str]] = {field: [] for field in FACET_FIELDS}
        warnings: list[str] = []
        seen_paths: set[Path] = set()
        action_nodes = [node for node in asset.node_info.nodes if node.role == "action"]
        for action in action_nodes:
            classify_path = self._find_classify_path(action)
            if classify_path is None or classify_path in seen_paths:
                continue
            seen_paths.add(classify_path)
            try:
                stat = classify_path.stat()
                mtime_ns = stat.st_mtime_ns
                cached_yaml = self._yaml_cache.get(classify_path)
                if cached_yaml is not None and cached_yaml[0] == mtime_ns:
                    data = cached_yaml[1]
                else:
                    data = yaml.safe_load(classify_path.read_text(encoding="utf-8-sig")) or {}
                    self._yaml_cache[classify_path] = (mtime_ns, data)
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                warnings.append(f"classify.yaml 读取失败：{classify_path}：{exc}")
                continue
            if not isinstance(data, dict):
                warnings.append(f"classify.yaml 顶层不是对象：{classify_path}")
                continue
            for field in FACET_FIELDS:
                values[field].extend(_flatten_facet_values(field, data.get(field)))

        result = ({field: _ordered_unique(items) for field, items in values.items()}, warnings)
        self._asset_cache[asset.asset_id] = result
        return result

    def _find_classify_path(self, action: ImageNodeRef) -> Path | None:
        if not action.ref:
            return None
        ref_key = action.ref.strip()
        if ref_key in self._path_cache:
            return self._path_cache[ref_key]
        start = Path(ref_key).expanduser()
        if not start.is_absolute():
            self._path_cache[ref_key] = None
            return None
        start = start if start.is_dir() else start.parent
        found: Path | None = None
        for directory in (start, *start.parents):
            candidate = directory / "classify.yaml"
            if candidate.is_file():
                found = candidate.resolve()
                break
        self._path_cache[ref_key] = found
        return found


@dataclass
class _PrecomputedSearchEntry:
    asset: AssetRecord
    values: dict[str, list[str]]
    facets: dict[str, list[str]]
    facet_warnings: list[str]
    sort_key: tuple
    combined_text: str


_SEARCH_ENTRIES_CACHE: dict[tuple[str, int, str | None], list[_PrecomputedSearchEntry]] = {}


class AssetSearchService:
    def __init__(self, *, facet_reader: ClassifyFacetReader | None = None):
        self.facet_reader = facet_reader or ClassifyFacetReader()

    def search(
        self,
        root: str | Path,
        filters: AssetSearchFilter,
    ) -> list[AssetSearchResult]:
        """保留旧数组接口，始终从匹配结果的第一条开始返回。"""
        return self._search_matches(root, filters)[: filters.limit]

    def search_page(
        self,
        root: str | Path,
        filters: AssetSearchFilter,
    ) -> AssetPageResult:
        """先完成全部过滤和稳定排序，再执行 offset/limit 分页。"""
        matches = self._search_matches(root, filters)
        start = filters.offset
        end = start + filters.limit
        items = matches[start:end]
        next_offset = end if end < len(matches) else None
        return AssetPageResult(
            items=items,
            offset=filters.offset,
            limit=filters.limit,
            has_more=next_offset is not None,
            next_offset=next_offset,
        )

    def preload(self, root: str | Path) -> None:
        """在后端服务启动时全量预热全局及所有导入快照的检索索引。"""
        paths, config = load_workspace(root)
        self._get_search_entries(paths, config, None)
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        for import_id, _ in catalog.import_sources():
            self._get_search_entries(paths, config, import_id)

    def _get_search_entries(
        self,
        paths,
        config,
        import_id: str | None,
    ) -> list[_PrecomputedSearchEntry]:
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        try:
            stat = catalog.path.stat()
            mtime_ns = stat.st_mtime_ns
        except OSError:
            mtime_ns = 0

        cache_key = (str(catalog.path.resolve()), mtime_ns, import_id)
        cached = _SEARCH_ENTRIES_CACHE.get(cache_key)
        if cached is not None:
            return cached

        assets = catalog.assets_for_import(import_id)
        action_config = config.classification.action_resolution
        action_resolver = ActionNodeValueResolver(
            design_root=action_config.design_root,
            action_root_name=action_config.action_root_name,
            enabled=action_config.enabled,
        )

        entries: list[_PrecomputedSearchEntry] = []
        for asset in assets:
            values = self._node_values(asset, action_resolver)
            facets, facet_warnings = self.facet_reader.read(asset)
            sort_key = (
                asset.source_order,
                asset.display_name.casefold(),
                asset.asset_id,
            )
            combined_text = " ".join(
                [asset.display_name, *[value for items in values.values() for value in items]]
            ).casefold()
            entries.append(
                _PrecomputedSearchEntry(
                    asset=asset,
                    values=values,
                    facets=facets,
                    facet_warnings=facet_warnings,
                    sort_key=sort_key,
                    combined_text=combined_text,
                )
            )

        entries.sort(key=lambda item: item.sort_key)

        for k in list(_SEARCH_ENTRIES_CACHE):
            if k[0] == cache_key[0] and k[1] != cache_key[1]:
                del _SEARCH_ENTRIES_CACHE[k]

        _SEARCH_ENTRIES_CACHE[cache_key] = entries
        return entries

    def _search_matches(
        self,
        root: str | Path,
        filters: AssetSearchFilter,
    ) -> list[AssetSearchResult]:
        paths, config = load_workspace(root)
        entries = self._get_search_entries(paths, config, filters.import_id)

        text_filter = filters.text.casefold() if filters.text else ""
        artist_filter = filters.artist.casefold() if filters.artist else ""
        char_filter = filters.character.casefold() if filters.character else ""
        group_filter = filters.action_group.casefold() if filters.action_group else ""
        act_filter = filters.action.casefold() if filters.action else ""
        facets_filter = {
            k: {v.casefold() for v in vals}
            for k, vals in filters.facets.items()
            if vals
        }

        has_text = bool(text_filter)
        has_artist = bool(artist_filter)
        has_char = bool(char_filter)
        has_group = bool(group_filter)
        has_act = bool(act_filter)
        has_facets = bool(facets_filter)

        matched_entries: list[_PrecomputedSearchEntry] = []
        for entry in entries:
            if has_text and text_filter not in entry.combined_text:
                continue
            if has_artist and not any(artist_filter in v.casefold() for v in entry.values["artist"]):
                continue
            if has_char and not any(char_filter in v.casefold() for v in entry.values["character"]):
                continue
            if has_group and not any(group_filter in v.casefold() for v in entry.values["action_group"]):
                continue
            if has_act and not any(act_filter in v.casefold() for v in entry.values["action"]):
                continue
            if has_facets:
                mismatch = False
                for field, expected_set in facets_filter.items():
                    actual = {v.casefold() for v in entry.facets.get(field, [])}
                    if not actual.intersection(expected_set):
                        mismatch = True
                        break
                if mismatch:
                    continue

            matched_entries.append(entry)

        usage = self._usage_index(paths, config.image_extensions)
        result: list[AssetSearchResult] = []
        for entry in matched_entries:
            asset = entry.asset
            result.append(
                AssetSearchResult(
                    asset_id=asset.asset_id,
                    path=asset.path,
                    display_name=asset.display_name,
                    width=asset.image.width,
                    height=asset.image.height,
                    image_format=asset.image.format,
                    values=entry.values,
                    facets=entry.facets,
                    warnings=[*asset.warnings, *entry.facet_warnings],
                    usage=usage.get(asset.asset_id, []),
                )
            )
        return result

    def facets(
        self,
        root: str | Path,
        *,
        import_id: str | None = None,
    ) -> dict[str, list[str]]:
        paths, config = load_workspace(root)
        entries = self._get_search_entries(paths, config, import_id)
        result = {field: set() for field in FACET_FIELDS}
        for entry in entries:
            for field, values in entry.facets.items():
                result[field].update(values)
        return {field: sorted(values, key=str.casefold) for field, values in result.items()}

    @staticmethod
    def _node_values(
        asset: AssetRecord,
        action_resolver: ActionNodeValueResolver,
    ) -> dict[str, list[str]]:
        return {
            role: action_resolver.values_for(asset, role)
            if role in {"action", "action_group"}
            else asset.node_values(role)
            for role in NODE_FIELDS
        }


    @staticmethod
    def _matches(
        asset: AssetRecord,
        values: dict[str, list[str]],
        facets: dict[str, list[str]],
        filters: AssetSearchFilter,
    ) -> bool:
        combined = " ".join(
            [asset.display_name, *[value for items in values.values() for value in items]]
        ).casefold()
        if filters.text and filters.text.casefold() not in combined:
            return False
        for role in ("artist", "character", "action_group", "action"):
            expected = getattr(filters, role)
            if expected and not any(expected.casefold() in value.casefold() for value in values[role]):
                return False
        for field, expected_values in filters.facets.items():
            actual = {value.casefold() for value in facets.get(field, [])}
            if expected_values and not actual.intersection(
                {value.casefold() for value in expected_values}
            ):
                return False
        return True

    @staticmethod
    def _usage_index(paths, image_extensions: list[str]) -> dict[str, list[str]]:
        usage: dict[str, list[str]] = {}
        repository = PlanRepository()
        if paths.plans.is_dir():
            for plan_yaml in sorted(paths.plans.glob("*/plan.yaml")):
                month = plan_yaml.parent.name
                try:
                    plan = repository.load(PlanPaths.from_workspace(paths, month))
                except (OSError, UnicodeError, ValueError) as exc:
                    logger.warning("月度计划使用索引跳过：%s：%s", plan_yaml, exc)
                    continue
                for entry in plan.entries:
                    if not isinstance(entry.content, InlineContent):
                        continue
                    for asset_ids in entry.content.sets.values():
                        for asset_id in asset_ids:
                            _append_usage(usage, asset_id, f"plan:{month}/{entry.entry_id}")

        extensions = {extension.casefold() for extension in image_extensions}
        if paths.tasks.is_dir():
            for task_root in sorted(paths.tasks.iterdir(), key=lambda item: item.name.casefold()):
                task_yaml = task_root / "task.yaml"
                if not task_yaml.is_file():
                    continue
                try:
                    task_paths = TaskPaths.from_workspace(paths, task_root.name)
                    TaskRepository.load(task_paths)
                    selections = CurrentSelectionScanner().scan(task_paths, extensions)
                except (OSError, UnicodeError, ValueError) as exc:
                    logger.warning("投稿任务使用索引跳过：%s：%s", task_root, exc)
                    continue
                for selection, files in selections.items():
                    for item in files:
                        asset_id = f"sha256:{_cached_file_sha256(Path(item.absolute_path))}"
                        _append_usage(usage, asset_id, f"task:{task_root.name}/{selection}")
        return usage


class NodeSearchService:
    """从 Catalog 推导节点候选，不把节点选择状态写回 Catalog。"""

    def search(
        self,
        root: str | Path,
        *,
        role: str,
        query: str = "",
        import_id: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> NodeListResult:
        normalized_role = str(role or "").strip()
        if normalized_role not in NODE_FIELDS:
            raise ValueError(f"不支持的节点 role：{normalized_role}")
        if offset < 0:
            raise ValueError("offset 不能小于 0")
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间")

        paths, _ = load_workspace(root)
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        expected = str(query or "").strip().casefold()
        options: dict[str, NodeOption] = {}
        for node_id, ref in catalog.node_candidates(normalized_role, import_id):
            raw_value = node_id or _name_from_ref(ref) or ""
            name = DEFAULT_NODE_IDENTITY_NORMALIZER.normalize(normalized_role, raw_value)
            if not name or (expected and expected not in name.casefold()):
                continue
            key = name.casefold()
            if key in options:
                continue
            options[key] = NodeOption(role=normalized_role, name=name, ref=ref)

        ordered = sorted(options.values(), key=lambda item: (item.name.casefold(), item.name))
        page = ordered[offset : offset + limit]
        return NodeListResult(
            role=normalized_role,
            nodes=page,
            offset=offset,
            limit=limit,
            has_more=offset + limit < len(ordered),
        )


def _name_from_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    normalized = ref.replace("\\", "/").rstrip("/")
    return Path(normalized).name or None


def _flatten_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_values(item))
        return result
    if isinstance(value, bool):
        return [str(value).casefold()]
    text = str(value).strip()
    return [text] if text else []


def _flatten_facet_values(field: str, value: Any) -> list[str]:
    """统一读取普通 facet 和 subtype 的分组映射值。"""
    if field == "subtype":
        return _flatten_subtype_values(value)
    return _flatten_values(value)


def _flatten_subtype_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for items in value.values():
            result.extend(_flatten_subtype_values(items))
        return result
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_subtype_values(item))
        return result
    return _flatten_values(value)


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _append_usage(index: dict[str, list[str]], asset_id: str, source: str) -> None:
    values = index.setdefault(asset_id, [])
    if source not in values:
        values.append(source)


_FILE_SHA256_CACHE: dict[tuple[str, int, int], str] = {}


def _cached_file_sha256(path: Path) -> str:
    try:
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        cached = _FILE_SHA256_CACHE.get(key)
        if cached is not None:
            return cached
        digest = _sha256(path)
        _FILE_SHA256_CACHE[key] = digest
        return digest
    except OSError:
        return _sha256(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
