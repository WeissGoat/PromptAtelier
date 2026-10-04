"""出图尺寸选择，各渲染后端共用。

请求参数 size 是一个选择：
- random：从画风的预设里抽一个；
- portrait / landscape / square：竖 / 横 / 方，用画风对应的那一个；
- custom：用请求里的 width / height。
画风在 renderers.<backend>.size_presets 里声明自己的竖横方尺寸（不同模型适合的尺寸不一样），
没声明时用 STANDARD_SIZE_PRESETS。请求没给 size 时用画风的 default_size，再没有就是 custom（保持 CLI / API 原来的行为）。
"""

from __future__ import annotations

from typing import Any

SIZE_RANDOM = "random"
SIZE_CUSTOM = "custom"
SIZE_ORIENTATIONS = ("portrait", "landscape", "square")
SIZE_CHOICES = (SIZE_RANDOM, *SIZE_ORIENTATIONS, SIZE_CUSTOM)

# NovelAI 的标准尺寸，也是 SDXL 常用的桶尺寸。
STANDARD_SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "portrait": (832, 1216),
    "landscape": (1216, 832),
    "square": (1024, 1024),
}


def size_presets(payload: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """画风声明的竖横方尺寸；没声明时用标准尺寸。"""
    value = payload.get("size_presets")
    if value is None:
        return dict(STANDARD_SIZE_PRESETS)
    if not isinstance(value, dict) or not value:
        raise ValueError("size_presets must map portrait/landscape/square to {width, height}")
    presets: dict[str, tuple[int, int]] = {}
    for orientation, item in value.items():
        if orientation not in SIZE_ORIENTATIONS:
            raise ValueError(f"size_presets keys must be portrait, landscape or square, got {orientation!r}")
        try:
            width, height = int(item["width"]), int(item["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"size_presets.{orientation} needs integer width and height") from exc
        if width < 64 or height < 64 or width % 8 or height % 8:
            raise ValueError(f"size_presets.{orientation} must be multiples of 8 and at least 64: {width}x{height}")
        presets[orientation] = (width, height)
    return presets


def resolve_render_size(
    payload: dict[str, Any],
    params: dict[str, Any],
    *,
    width: int,
    height: int,
    rng: Any,
) -> tuple[int, int, str | None, dict[str, Any]]:
    """按 params.size 定宽高；返回 (宽, 高, 用了哪个预设或 None, 去掉 size 的 params)。"""
    remaining = dict(params)
    raw = remaining.pop("size", None)
    choice = str(raw or payload.get("default_size") or SIZE_CUSTOM).strip()
    if choice not in SIZE_CHOICES:
        raise ValueError(f"size must be one of {', '.join(SIZE_CHOICES)}, got {choice!r}")
    if choice == SIZE_CUSTOM:
        return width, height, None, remaining
    presets = size_presets(payload)
    if choice == SIZE_RANDOM:
        choice = rng.choice(sorted(presets))
    if choice not in presets:
        available = ", ".join(sorted(presets))
        raise ValueError(f"this artist has no {choice} size preset (available: {available})")
    chosen_width, chosen_height = presets[choice]
    return chosen_width, chosen_height, choice, remaining
