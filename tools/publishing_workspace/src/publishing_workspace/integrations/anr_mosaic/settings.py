from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_DETECTORS = frozenset({"yolo", "yolo_sam"})
SUPPORTED_METHODS = frozenset({"pixel", "blur", "line", "solid", "emoji"})
SUPPORTED_PARTS = frozenset({"penis", "pussy", "female_nipple", "anus"})
DETECTOR_LABELS = {
    "penis": "penis",
    "pussy": "pussy",
    "female_nipple": "nipple_f",
}


@dataclass(frozen=True)
class MosaicSettings:
    detector: str
    method: str
    parts: tuple[str, ...]
    pixel_size: int = 15
    blur_radius: int = 12
    line_width_range: tuple[int, int] = (1, 4)
    line_spacing_range: tuple[int, int] = (3, 8)
    color: tuple[int, int, int] = (128, 128, 128)
    emoji_dir: Path | None = None

    @classmethod
    def from_options(cls, options: dict[str, Any], *, default_emoji_dir: Path) -> "MosaicSettings":
        detector = str(options.get("detector", "yolo_sam")).strip().casefold()
        if detector not in SUPPORTED_DETECTORS:
            raise ValueError(
                f"mosaic.detector 不支持：{detector}，可选值为 yolo、yolo_sam"
            )

        method = str(options.get("method", "pixel")).strip().casefold()
        if method not in SUPPORTED_METHODS:
            raise ValueError(
                f"mosaic.method 不支持：{method}，可选值为 "
                "pixel、blur、line、solid、emoji"
            )

        parts = _parts(options.get("parts", ("penis", "pussy")))
        return cls(
            detector=detector,
            method=method,
            parts=parts,
            pixel_size=_bounded_int(options.get("pixel_size", 15), "pixel_size", 1, 100),
            blur_radius=_bounded_int(options.get("blur_radius", 12), "blur_radius", 1, 100),
            line_width_range=_range(
                options.get("line_width_range", (1, 4)), "line_width_range", 1, 100
            ),
            line_spacing_range=_range(
                options.get("line_spacing_range", (3, 8)), "line_spacing_range", 1, 100
            ),
            color=_color(options.get("color", (128, 128, 128))),
            emoji_dir=Path(options["emoji_dir"]).expanduser() if options.get("emoji_dir") else default_emoji_dir,
        )

    @property
    def detector_labels(self) -> tuple[str, ...]:
        return tuple(DETECTOR_LABELS[part] for part in self.parts if part in DETECTOR_LABELS)

    @property
    def unsupported_detector_parts(self) -> tuple[str, ...]:
        return tuple(part for part in self.parts if part not in DETECTOR_LABELS)


def _parts(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        raise ValueError("mosaic.parts 必须是字符串或列表")
    normalized = tuple(dict.fromkeys(item.casefold() for item in items if item))
    if not normalized:
        raise ValueError("mosaic.parts 不能为空")
    unknown = sorted(set(normalized) - SUPPORTED_PARTS)
    if unknown:
        raise ValueError(f"mosaic.parts 存在不支持的部位：{', '.join(unknown)}")
    return normalized


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"mosaic.{name} 必须是整数")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"mosaic.{name} 必须是整数") from exc
    if not minimum <= normalized <= maximum:
        raise ValueError(f"mosaic.{name} 必须在 {minimum}-{maximum} 之间")
    return normalized


def _range(value: Any, name: str, minimum: int, maximum: int) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"mosaic.{name} 必须是两个整数")
    result = (
        _bounded_int(value[0], name, minimum, maximum),
        _bounded_int(value[1], name, minimum, maximum),
    )
    if result[0] > result[1]:
        raise ValueError(f"mosaic.{name} 的最小值不能大于最大值")
    return result


def _color(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("mosaic.color 必须是三个整数")
    return tuple(_bounded_int(item, "color", 0, 255) for item in value)  # type: ignore[return-value]


__all__ = [
    "DETECTOR_LABELS",
    "MosaicSettings",
    "SUPPORTED_DETECTORS",
    "SUPPORTED_METHODS",
    "SUPPORTED_PARTS",
]
