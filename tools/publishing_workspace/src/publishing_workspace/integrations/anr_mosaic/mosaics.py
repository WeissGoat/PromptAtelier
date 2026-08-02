from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from ...logging import get_logger
from .settings import MosaicSettings


logger = get_logger(__name__)


class ImageMosaicProcessor:
    def process(
        self,
        source: Path,
        mask_path: Path,
        target: Path,
        settings: MosaicSettings,
    ) -> None:
        image, mask = self._load_images(source, mask_path)
        if settings.method == "pixel":
            result = self._pixel(image, mask, settings.pixel_size)
        elif settings.method == "blur":
            result = self._blur(image, mask, settings.blur_radius)
        elif settings.method == "line":
            result = self._line(image, mask, settings.line_width_range, settings.line_spacing_range)
        elif settings.method == "solid":
            result = self._solid(image, mask, settings.color)
        elif settings.method == "emoji":
            result = self._emoji(image, mask, settings.emoji_dir)
        else:
            raise ValueError(f"不支持的打码方法：{settings.method}")
        target.parent.mkdir(parents=True, exist_ok=True)
        result.save(target, format=_format_for_path(target))

    def _load_images(self, source: Path, mask_path: Path) -> tuple[Image.Image, Image.Image]:
        try:
            image = Image.open(source).convert("RGB")
            mask = Image.open(mask_path).convert("L")
        except (OSError, ValueError) as exc:
            raise ValueError(f"无法读取打码输入：{source}，{mask_path}") from exc
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.Resampling.NEAREST)
        return image, mask

    def _pixel(self, image: Image.Image, mask: Image.Image, pixel_size: int) -> Image.Image:
        np = _numpy()
        image_array = np.array(image)
        mask_array = np.array(mask)
        result = image_array.copy()
        masked = mask_array > 200
        height, width = image_array.shape[:2]
        for y in range(0, height, pixel_size):
            for x in range(0, width, pixel_size):
                y_end = min(y + pixel_size, height)
                x_end = min(x + pixel_size, width)
                if np.any(masked[y:y_end, x:x_end]):
                    block = image_array[y:y_end, x:x_end]
                    result[y:y_end, x:x_end] = np.mean(block, axis=(0, 1)).astype(int)
        return Image.fromarray(result)

    def _blur(self, image: Image.Image, mask: Image.Image, radius: int) -> Image.Image:
        result = image.copy()
        result.paste(image.filter(ImageFilter.GaussianBlur(radius)), (0, 0), mask)
        return result

    def _solid(
        self,
        image: Image.Image,
        mask: Image.Image,
        color: tuple[int, int, int],
    ) -> Image.Image:
        result = image.copy()
        result.paste(Image.new("RGB", image.size, color), (0, 0), mask)
        return result

    def _line(
        self,
        image: Image.Image,
        mask: Image.Image,
        width_range: tuple[int, int],
        spacing_range: tuple[int, int],
    ) -> Image.Image:
        np = _numpy()
        regions = _connected_components(np.array(mask))
        color = "white" if self._brightness(image) < 128 else "black"
        result = image.copy()
        draw = ImageDraw.Draw(result)
        for min_x, min_y, max_x, max_y in regions:
            region_width = max_x - min_x
            region_height = max_y - min_y
            if min(region_width, region_height) < 10:
                continue
            if region_width > region_height:
                self._vertical_lines(
                    draw,
                    min_x,
                    min_y,
                    max_x,
                    max_y,
                    width_range,
                    spacing_range,
                    color,
                )
            else:
                self._horizontal_lines(
                    draw,
                    min_x,
                    min_y,
                    max_x,
                    max_y,
                    width_range,
                    spacing_range,
                    color,
                )
        return result

    def _emoji(
        self,
        image: Image.Image,
        mask: Image.Image,
        emoji_dir: Path | None,
    ) -> Image.Image:
        if emoji_dir is None or not emoji_dir.is_dir():
            raise ValueError(f"emoji 目录不存在：{emoji_dir}")
        emoji_paths = sorted(
            path
            for path in emoji_dir.iterdir()
            if path.is_file() and path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}
        )
        if not emoji_paths:
            raise ValueError(f"emoji 目录没有可用图片：{emoji_dir}")
        emojis = [Image.open(path).convert("RGB") for path in emoji_paths]
        try:
            result = image.copy()
            for index, (min_x, min_y, max_x, max_y) in enumerate(
                _connected_components(_numpy().array(mask))
            ):
                region_width = max_x - min_x
                region_height = max_y - min_y
                if min(region_width, region_height) < 10:
                    continue
                result.paste(
                    emojis[index % len(emojis)].resize((region_width, region_height)),
                    (min_x, min_y),
                )
            return result
        finally:
            for emoji in emojis:
                emoji.close()

    @staticmethod
    def _brightness(image: Image.Image) -> float:
        np = _numpy()
        return float(np.mean(np.array(image.convert("L"))))

    @staticmethod
    def _horizontal_lines(
        draw: ImageDraw.ImageDraw,
        min_x: int,
        min_y: int,
        max_x: int,
        max_y: int,
        width_range: tuple[int, int],
        spacing_range: tuple[int, int],
        color: str,
    ) -> None:
        height = max_y - min_y
        width = max_x - min_x
        min_width, max_width = width_range
        _, max_spacing = spacing_range
        count = max(3, int(height / (max_spacing + max_width)))
        spacing = height / count
        base_width = max(min_width, min(max_width, min_width + (max_width - min_width) * height / 500))
        for index in range(count):
            y = min_y + index * spacing + spacing / 2
            relative = (y - min_y) / max(height, 1)
            factor = _edge_factor(relative)
            line_length = width * factor
            current_width = max(1, int(max(min_width, min(max_width, base_width * (0.5 + factor * 0.5)))))
            draw.line(
                [(min_x + (width - line_length) / 2, y), (min_x + (width + line_length) / 2, y)],
                fill=color,
                width=current_width,
            )

    @staticmethod
    def _vertical_lines(
        draw: ImageDraw.ImageDraw,
        min_x: int,
        min_y: int,
        max_x: int,
        max_y: int,
        width_range: tuple[int, int],
        spacing_range: tuple[int, int],
        color: str,
    ) -> None:
        height = max_y - min_y
        width = max_x - min_x
        min_width, max_width = width_range
        _, max_spacing = spacing_range
        count = max(3, int(width / (max_spacing + max_width)))
        spacing = width / count
        base_width = max(min_width, min(max_width, min_width + (max_width - min_width) * width / 500))
        for index in range(count):
            x = min_x + index * spacing + spacing / 2
            relative = (x - min_x) / max(width, 1)
            factor = _edge_factor(relative)
            line_length = height * factor
            current_width = max(1, int(max(min_width, min(max_width, base_width * (0.5 + factor * 0.5)))))
            draw.line(
                [(x, min_y + (height - line_length) / 2), (x, min_y + (height + line_length) / 2)],
                fill=color,
                width=current_width,
            )


def _connected_components(mask_array: Any) -> list[tuple[int, int, int, int]]:
    try:
        from scipy import ndimage
    except ImportError as exc:
        raise RuntimeError(
            "line/emoji 打码需要安装 mosaic extra：uv sync --extra mosaic"
        ) from exc
    labeled, count = ndimage.label(mask_array > 200)
    regions: list[tuple[int, int, int, int]] = []
    for index in range(1, count + 1):
        ys, xs = (labeled == index).nonzero()
        if len(xs):
            regions.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    return regions


def _edge_factor(relative: float) -> float:
    if relative < 0.25:
        return relative / 0.25
    if relative > 0.75:
        return (1.0 - relative) / 0.25
    return 1.0


def _numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "mosaic 打码需要安装 mosaic extra：uv sync --extra mosaic"
        ) from exc
    return np


def _format_for_path(path: Path) -> str:
    formats = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
    try:
        return formats[path.suffix.casefold()]
    except KeyError as exc:
        raise ValueError(f"无法判断图片格式：{path}") from exc


__all__ = ["ImageMosaicProcessor"]
