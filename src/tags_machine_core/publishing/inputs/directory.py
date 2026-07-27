from __future__ import annotations

import re
from pathlib import Path

from ..models import SelectionSet
from .base import InputContext
from .shortcut import imported_item_from_path


def natural_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    )


class DirectoryInputAdapter:
    type = "directory"

    def probe(self, source: Path) -> bool:
        return source.is_dir()

    def load(self, source: Path, context: InputContext) -> SelectionSet:
        if not source.is_dir():
            raise NotADirectoryError(f"输入不是目录：{source}")
        candidates = source.rglob("*") if context.recursive else source.glob("*")
        files = [
            path
            for path in candidates
            if path.is_file()
            and (context.supports_image(path) or path.suffix.casefold() == ".lnk")
        ]
        files.sort(key=lambda path: natural_key(str(path.relative_to(source))))
        items = [
            imported_item_from_path(
                path,
                source_type=self.type,
                source_ref=str(source),
                source_order=index,
                context=context,
            )
            for index, path in enumerate(files)
        ]
        warnings = [warning for item in items for warning in item.warnings]
        return SelectionSet(
            source_type=self.type,
            source_ref=str(source),
            items=items,
            warnings=warnings,
        )
