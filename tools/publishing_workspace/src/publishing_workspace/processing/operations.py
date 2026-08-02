from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from .models import ImageOperation, MosaicAdapter


class StripMetadataOperation:
    type = "strip_metadata"
    version = "1"

    def validate(self, options: dict[str, Any]) -> None:
        return None

    def process(
        self,
        input_path: Path,
        output_path: Path,
        options: dict[str, Any],
    ) -> None:
        try:
            with Image.open(input_path) as image:
                image.load()
                image_format = image.format or _format_for_path(output_path)
                image.save(output_path, format=image_format)
        except (OSError, ValueError) as exc:
            raise ValueError(f"清除图片参数失败：{input_path}：{exc}") from exc


class MosaicOperation:
    type = "mosaic"
    version = "2"

    def __init__(self, adapters: dict[str, MosaicAdapter] | None = None):
        self.adapters = adapters or {}

    def validate(self, options: dict[str, Any]) -> None:
        adapter_name = str(options.get("adapter") or "").strip()
        if not adapter_name:
            raise ValueError("mosaic 已启用，但没有配置 adapter")
        if adapter_name not in self.adapters:
            raise ValueError(f"mosaic adapter 不存在：{adapter_name}")

        validator = getattr(self.adapters[adapter_name], "validate", None)
        if callable(validator):
            validator(dict(options.get("options") or {}))

    def process(
        self,
        input_path: Path,
        output_path: Path,
        options: dict[str, Any],
    ) -> None:
        self.validate(options)
        adapter = self.adapters[str(options["adapter"])]
        adapter.process(input_path, output_path, dict(options.get("options") or {}))


class OperationRegistry:
    def __init__(self, operations: list[ImageOperation] | None = None):
        self._operations: dict[str, ImageOperation] = {}
        for operation in operations or []:
            self.register(operation)

    def register(self, operation: ImageOperation) -> None:
        if operation.type in self._operations:
            raise ValueError(f"图片 Operation 重复注册：{operation.type}")
        self._operations[operation.type] = operation

    def get(self, operation_type: str) -> ImageOperation:
        try:
            return self._operations[operation_type]
        except KeyError as exc:
            raise ValueError(f"未知图片 Operation：{operation_type}") from exc


def default_operation_registry(
    mosaic_adapters: dict[str, MosaicAdapter] | None = None,
) -> OperationRegistry:
    return OperationRegistry(
        [
            StripMetadataOperation(),
            MosaicOperation(mosaic_adapters),
        ]
    )


def _format_for_path(path: Path) -> str:
    formats = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".webp": "WEBP",
    }
    try:
        return formats[path.suffix.casefold()]
    except KeyError as exc:
        raise ValueError(f"无法判断图片格式：{path}") from exc
