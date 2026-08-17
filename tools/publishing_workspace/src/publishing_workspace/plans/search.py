from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from ..action_resolution import ActionNodeValueResolver
from ..catalog.repository import CatalogRepository
from ..config import load_workspace
from ..logging import get_logger
from ..models import AssetRecord, ImageNodeRef
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
    values: dict[str, list[str]]
    facets: dict[str, list[str]]
    warnings: list[str] = Field(default_factory=list)
    usage: list[str] = Field(default_factory=list)


class ClassifyFacetReader:
    """从 action 节点目录附近的 classify.yaml 读取检索字段。"""

    def read(self, asset: AssetRecord) -> tuple[dict[str, list[str]], list[str]]:
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
                data = yaml.safe_load(classify_path.read_text(encoding="utf-8-sig")) or {}
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                warnings.append(f"classify.yaml 读取失败：{classify_path}：{exc}")
                continue
            if not isinstance(data, dict):
                warnings.append(f"classify.yaml 顶层不是对象：{classify_path}")
                continue
            for field in FACET_FIELDS:
                values[field].extend(_flatten_values(data.get(field)))
        return {field: _ordered_unique(items) for field, items in values.items()}, warnings

    @staticmethod
    def _find_classify_path(action: ImageNodeRef) -> Path | None:
        if not action.ref:
            return None
        start = Path(action.ref).expanduser()
        if not start.is_absolute():
            return None
        start = start if start.is_dir() else start.parent
        for directory in (start, *start.parents):
            candidate = directory / "classify.yaml"
            if candidate.is_file():
                return candidate.resolve()
        return None


class AssetSearchService:
    def __init__(self, *, facet_reader: ClassifyFacetReader | None = None):
        self.facet_reader = facet_reader or ClassifyFacetReader()

    def search(
        self,
        root: str | Path,
        filters: AssetSearchFilter,
    ) -> list[AssetSearchResult]:
        paths, config = load_workspace(root)
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        assets = catalog.assets_for_import(filters.import_id)
        action_config = config.classification.action_resolution
        action_resolver = ActionNodeValueResolver(
            design_root=action_config.design_root,
            action_root_name=action_config.action_root_name,
            enabled=action_config.enabled,
        )
        usage = self._usage_index(paths, config.image_extensions)
        result: list[AssetSearchResult] = []
        for asset in assets:
            values = self._node_values(asset, action_resolver)
            facets, facet_warnings = self.facet_reader.read(asset)
            if not self._matches(asset, values, facets, filters):
                continue
            result.append(
                AssetSearchResult(
                    asset_id=asset.asset_id,
                    path=asset.path,
                    display_name=asset.display_name,
                    values=values,
                    facets=facets,
                    warnings=[*asset.warnings, *facet_warnings],
                    usage=usage.get(asset.asset_id, []),
                )
            )
            if len(result) >= filters.limit:
                break
        return result

    def facets(
        self,
        root: str | Path,
        *,
        import_id: str | None = None,
    ) -> dict[str, list[str]]:
        paths, _ = load_workspace(root)
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        result = {field: set() for field in FACET_FIELDS}
        for asset in catalog.assets_for_import(import_id):
            facets, _ = self.facet_reader.read(asset)
            for field, values in facets.items():
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
                        asset_id = f"sha256:{_sha256(Path(item.absolute_path))}"
                        _append_usage(usage, asset_id, f"task:{task_root.name}/{selection}")
        return usage


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
