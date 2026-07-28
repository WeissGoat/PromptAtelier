from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from ..models import SelectionSet


class InputContext(BaseModel):
    recursive: bool = False
    strict: bool = False
    legacy_tolerant: bool = False
    image_extensions: set[str] = Field(
        default_factory=lambda: {".png", ".jpg", ".jpeg", ".webp"}
    )

    def supports_image(self, path: Path) -> bool:
        return path.suffix.casefold() in {item.casefold() for item in self.image_extensions}


class InputAdapter(Protocol):
    type: str

    def probe(self, source: Path) -> bool: ...

    def load(self, source: Path, context: InputContext) -> SelectionSet: ...


class InputAdapterRegistry:
    def __init__(self, adapters: list[InputAdapter] | None = None):
        self._adapters: dict[str, InputAdapter] = {}
        for adapter in adapters or []:
            self.register(adapter)

    def register(self, adapter: InputAdapter) -> None:
        if adapter.type in self._adapters:
            raise ValueError(f"输入适配器重复注册：{adapter.type}")
        self._adapters[adapter.type] = adapter

    @property
    def types(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def load(
        self,
        source: str | Path,
        *,
        input_type: str | None = None,
        context: InputContext | None = None,
    ) -> SelectionSet:
        path = Path(source).expanduser().resolve()
        adapter = self._select(path, input_type=input_type)
        return adapter.load(path, context or InputContext())

    def _select(self, source: Path, *, input_type: str | None) -> InputAdapter:
        if input_type:
            adapter = self._adapters.get(input_type)
            if adapter is None:
                raise ValueError(
                    f"未知输入类型：{input_type}；可选值：{', '.join(self.types)}"
                )
            return adapter
        for adapter in self._adapters.values():
            if adapter.probe(source):
                return adapter
        raise ValueError(f"无法识别 Publishing 输入类型：{source}")


def default_input_registry() -> InputAdapterRegistry:
    from .directory import DirectoryInputAdapter
    from .neev_playlist import NeeViewPlaylistInputAdapter
    from .shortcut import ShortcutInputAdapter

    return InputAdapterRegistry(
        [
            NeeViewPlaylistInputAdapter(),
            DirectoryInputAdapter(),
            ShortcutInputAdapter(),
        ]
    )
