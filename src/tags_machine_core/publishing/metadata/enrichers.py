from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ..models import ImageNodeInfo, ImageNodeRef


class ImageNodeInfoEnricher(Protocol):
    id: str

    def enrich(self, image_path: Path, node_info: ImageNodeInfo) -> ImageNodeInfo: ...


class ActionGroupManifestEnricher:
    """通过 Action 分类 manifest 补全 action_group，不改变 Reader 原始解析。"""

    id = "action_group_manifest"

    def __init__(self) -> None:
        self._manifest_cache: dict[Path, list[dict]] = {}

    def enrich(self, image_path: Path, node_info: ImageNodeInfo) -> ImageNodeInfo:
        if node_info.values_for("action_group"):
            return node_info
        action_nodes = [node for node in node_info.nodes if node.role == "action"]
        groups: list[tuple[str, str]] = []
        warnings = list(node_info.warnings)
        for action in action_nodes:
            try:
                groups.extend(self._groups_for(action))
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                warnings.append(f"Action group manifest 解析失败：{action.ref or action.id}：{exc}")
        groups = _ordered_unique_groups(groups)
        if not groups:
            return node_info.model_copy(update={"warnings": warnings})
        nodes = list(node_info.nodes)
        nodes.extend(
            ImageNodeRef(role="action_group", id=name, ref=ref, index=index)
            for index, (name, ref) in enumerate(groups)
        )
        return node_info.model_copy(update={"nodes": nodes, "warnings": warnings})

    def _groups_for(self, action: ImageNodeRef) -> list[tuple[str, str]]:
        if not action.ref:
            return []
        action_path = Path(action.ref).expanduser()
        if not action_path.is_absolute():
            return []
        manifest_path = _find_manifest(action_path)
        if manifest_path is None:
            return []
        action_root = manifest_path.parent
        try:
            relative = action_path.resolve().relative_to(action_root.resolve()).as_posix()
        except ValueError:
            return []
        items = self._read_manifest(manifest_path)
        groups: list[tuple[str, str]] = []
        for item in items:
            source = _normalize_relative(item.get("source"))
            dest = _normalize_relative(item.get("dest"))
            action_name = action.id or action_path.name
            if relative not in {source, dest} and action_name not in {
                Path(source).name if source else "",
                Path(dest).name if dest else "",
            }:
                continue
            root = str(item.get("root") or "").strip()
            if root:
                groups.append((root, str((action_root / root).resolve())))
        return groups

    def _read_manifest(self, path: Path) -> list[dict]:
        resolved = path.resolve()
        cached = self._manifest_cache.get(resolved)
        if cached is not None:
            return cached
        data = json.loads(resolved.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError(f"manifest 顶层必须包含 items 数组：{resolved}")
        items = [item for item in data["items"] if isinstance(item, dict)]
        self._manifest_cache[resolved] = items
        return items


def _find_manifest(action_path: Path) -> Path | None:
    start = action_path if action_path.is_dir() else action_path.parent
    for candidate in (start, *start.parents):
        manifest = candidate / "category_view_manifest.json"
        if manifest.is_file():
            return manifest
    return None


def _normalize_relative(value) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _ordered_unique_groups(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, ref in values:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append((name, ref))
    return result
