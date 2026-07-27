from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import SelectionSet
from .base import InputContext
from .shortcut import imported_item_from_path


class NeeViewPlaylistInputAdapter:
    type = "neev_playlist"

    def probe(self, source: Path) -> bool:
        return source.is_file() and source.suffix.casefold() == ".nvpls"

    def load(self, source: Path, context: InputContext) -> SelectionSet:
        if not source.is_file():
            raise FileNotFoundError(f"NeeView 播放列表不存在：{source}")
        data, parse_warnings = _read_playlist(source, tolerant=context.legacy_tolerant)
        fmt = data.get("Format")
        if fmt != "NeeView.Playlist/2.0.0":
            raise ValueError(f"不支持的 NeeView 播放列表格式：{fmt!r}")
        raw_items = data.get("Items")
        if not isinstance(raw_items, list):
            raise ValueError(f"NeeView 播放列表 Items 必须是数组：{source}")

        items = []
        warnings = list(parse_warnings)
        for index, raw_item in enumerate(raw_items):
            path_value = raw_item.get("Path") if isinstance(raw_item, dict) else None
            if not isinstance(path_value, str) or not path_value.strip():
                message = f"NeeView Items[{index}].Path 缺失或不是字符串"
                if context.strict:
                    raise ValueError(message)
                warnings.append(message)
                continue
            item = imported_item_from_path(
                path_value,
                source_type=self.type,
                source_ref=str(source),
                source_order=index,
                context=context,
            )
            items.append(item)
            warnings.extend(item.warnings)
        return SelectionSet(
            source_type=self.type,
            source_ref=str(source),
            items=items,
            warnings=warnings,
        )


def _read_playlist(path: Path, *, tolerant: bool) -> tuple[dict[str, Any], list[str]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"无法读取 NeeView 播放列表：{path}：{exc}") from exc
    try:
        data = json.loads(text)
        warnings: list[str] = []
    except json.JSONDecodeError as strict_error:
        if not tolerant:
            raise ValueError(
                f"NeeView 播放列表 JSON 无效：{path}："
                f"第 {strict_error.lineno} 行第 {strict_error.colno} 列：{strict_error.msg}"
            ) from strict_error
        try:
            data = json.loads(text, strict=False)
        except json.JSONDecodeError as tolerant_error:
            raise ValueError(
                f"NeeView 播放列表即使在 legacy_tolerant 模式下也无法解析：{path}："
                f"第 {tolerant_error.lineno} 行第 {tolerant_error.colno} 列：{tolerant_error.msg}"
            ) from tolerant_error
        warnings = ["播放列表使用 legacy_tolerant JSON 模式解析"]
    if not isinstance(data, dict):
        raise ValueError(f"NeeView 播放列表顶层必须是对象：{path}")
    return data, warnings
