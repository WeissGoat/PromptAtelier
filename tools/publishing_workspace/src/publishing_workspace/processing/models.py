from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from ..tasks.models import OperationConfig, ProcessingConfig


class ImageOperation(Protocol):
    type: str
    version: str

    def validate(self, options: dict[str, Any]) -> None: ...

    def process(
        self,
        input_path: Path,
        output_path: Path,
        options: dict[str, Any],
    ) -> None: ...


class MosaicAdapter(Protocol):
    name: str

    def process(
        self,
        source: Path,
        target: Path,
        options: dict[str, Any],
    ) -> None: ...


class ProcessingResult(BaseModel):
    output_path: str
    cache_hit: bool = False
    processed_operations: list[str] = Field(default_factory=list)
    skipped_operations: list[str] = Field(default_factory=list)


__all__ = [
    "ImageOperation",
    "MosaicAdapter",
    "OperationConfig",
    "ProcessingConfig",
    "ProcessingResult",
]
