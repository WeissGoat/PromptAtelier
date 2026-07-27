from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import ImageNodeInfo
from .readers import (
    CoreImageNodeReader,
    ImageNodeReadError,
    ImageNodeReader,
    LegacyImageNodeReader,
)


class ImageNodeReaderRegistry:
    def __init__(self, readers: list[ImageNodeReader] | None = None):
        self._readers = sorted(readers or [], key=lambda item: item.priority, reverse=True)

    def register(self, reader: ImageNodeReader) -> None:
        if any(item.id == reader.id for item in self._readers):
            raise ValueError(f"图片节点 Reader 重复注册：{reader.id}")
        self._readers.append(reader)
        self._readers.sort(key=lambda item: item.priority, reverse=True)

    def read(self, image_path: str | Path, metadata: dict[str, Any]) -> ImageNodeInfo:
        path = Path(image_path)
        recoverable_warnings: list[str] = []
        for reader in self._readers:
            if not reader.supports(metadata):
                continue
            try:
                result = reader.read(path, metadata)
            except (ImageNodeReadError, UnicodeError, TypeError, ValueError) as exc:
                recoverable_warnings.append(f"{reader.id} Reader 读取失败：{exc}")
                continue
            result.warnings = recoverable_warnings + result.warnings
            return result
        return ImageNodeInfo(
            format="unknown",
            reader="unknown",
            warnings=recoverable_warnings + ["图片没有可识别的新旧节点元数据"],
        )


def default_image_node_reader_registry() -> ImageNodeReaderRegistry:
    return ImageNodeReaderRegistry([CoreImageNodeReader(), LegacyImageNodeReader()])
