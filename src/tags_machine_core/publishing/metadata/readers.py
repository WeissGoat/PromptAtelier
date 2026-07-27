from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from ..models import ImageNodeInfo, ImageNodeRef


CORE_METADATA_KEY = "tags_machine_core"
CORE_SCHEMA_V1 = "tags-machine-core.png-info/v1"
LEGACY_ROLES = {
    "artist": "artist",
    "character": "character",
    "action": "action",
    "topic": "action_group",
    "background": "background",
}


class ImageNodeReadError(ValueError):
    """图片内嵌节点信息存在但无法读取。"""


class ImageNodeReader(Protocol):
    id: str
    priority: int

    def supports(self, metadata: dict[str, Any]) -> bool: ...

    def read(self, image_path: Path, metadata: dict[str, Any]) -> ImageNodeInfo: ...


class CoreImageNodeReader:
    id = "core"
    priority = 100

    def supports(self, metadata: dict[str, Any]) -> bool:
        return _metadata_value(metadata, CORE_METADATA_KEY) is not None

    def read(self, image_path: Path, metadata: dict[str, Any]) -> ImageNodeInfo:
        raw = _metadata_value(metadata, CORE_METADATA_KEY)
        data = _as_json_object(raw, field=CORE_METADATA_KEY)
        schema = data.get("schema")
        if schema != CORE_SCHEMA_V1:
            raise ImageNodeReadError(f"不支持的 core PNG schema：{schema!r}")

        raw_nodes = data.get("nodes") or []
        if not isinstance(raw_nodes, list):
            raise ImageNodeReadError("tags_machine_core.nodes 必须是数组")
        nodes = _structured_nodes(raw_nodes, source="nodes")

        source_nodes = data.get("source_nodes") or []
        if not isinstance(source_nodes, list):
            raise ImageNodeReadError("tags_machine_core.source_nodes 必须是数组")
        # 当前 source_nodes 通常只是路径数组；仅补充其中带 role 的结构化记录。
        nodes.extend(_structured_nodes(source_nodes, source="source_nodes", start=len(nodes)))
        nodes = _deduplicate_nodes(nodes)
        warnings: list[str] = []
        if not nodes and source_nodes:
            warnings.append("core PNG 只有无 role 的 source_nodes，无法用于结构化分类")
        return ImageNodeInfo(format="core", reader=self.id, nodes=nodes, warnings=warnings)


class LegacyImageNodeReader:
    id = "legacy"
    priority = 10

    def supports(self, metadata: dict[str, Any]) -> bool:
        keys = {str(key).casefold() for key in metadata}
        return any(key in keys for key in (*LEGACY_ROLES, "artist_path"))

    def read(self, image_path: Path, metadata: dict[str, Any]) -> ImageNodeInfo:
        normalized = {str(key).casefold(): value for key, value in metadata.items()}
        nodes: list[ImageNodeRef] = []
        warnings: list[str] = []

        artist_values = _legacy_values(normalized.get("artist"))
        artist_paths = _legacy_values(normalized.get("artist_path"))
        artist_count = max(len(artist_values), len(artist_paths))
        for index in range(artist_count):
            artist = artist_values[index] if index < len(artist_values) else None
            artist_path = artist_paths[index] if index < len(artist_paths) else None
            nodes.append(
                ImageNodeRef(
                    role="artist",
                    id=_node_id(artist) or _node_id(artist_path),
                    ref=artist_path or artist,
                    index=index,
                )
            )

        for legacy_key, role in LEGACY_ROLES.items():
            if legacy_key == "artist":
                continue
            values = _legacy_values(normalized.get(legacy_key))
            for index, value in enumerate(values):
                nodes.append(
                    ImageNodeRef(
                        role=role,
                        id=_node_id(value),
                        ref=value,
                        index=index,
                    )
                )
        if not nodes:
            warnings.append("图片没有可识别的旧版节点字段")
        return ImageNodeInfo(
            format="legacy",
            reader=self.id,
            nodes=_deduplicate_nodes(nodes),
            warnings=warnings,
        )


def _metadata_value(metadata: dict[str, Any], key: str) -> Any:
    target = key.casefold()
    for current, value in metadata.items():
        if str(current).casefold() == target:
            return value
    return None


def _as_json_object(value: Any, *, field: str) -> dict[str, Any]:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="strict")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ImageNodeReadError(
                f"{field} JSON 无效：第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}"
            ) from exc
    if not isinstance(value, dict):
        raise ImageNodeReadError(f"{field} 必须是 JSON 对象")
    return value


def _structured_nodes(
    values: list[Any],
    *,
    source: str,
    start: int = 0,
) -> list[ImageNodeRef]:
    result: list[ImageNodeRef] = []
    for fallback_index, value in enumerate(values, start=start):
        if not isinstance(value, dict):
            continue
        role = str(value.get("role") or "").strip()
        if not role:
            continue
        node_id = _clean_optional(value.get("id"))
        ref = _clean_optional(value.get("ref"))
        if not node_id and not ref:
            continue
        try:
            index = int(value.get("index", fallback_index))
        except (TypeError, ValueError):
            index = fallback_index
        result.append(ImageNodeRef(role=role, id=node_id, ref=ref, index=index))
    return result


def _legacy_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [text]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _node_id(value: str | None) -> str | None:
    text = _clean_optional(value)
    if not text:
        return None
    normalized = text.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1]


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _deduplicate_nodes(nodes: list[ImageNodeRef]) -> list[ImageNodeRef]:
    result: list[ImageNodeRef] = []
    seen: set[tuple[str, int, str, str]] = set()
    for node in nodes:
        key = (node.role, node.index, node.id or "", node.ref or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(node)
    return result
