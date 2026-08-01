from __future__ import annotations

import re
from pathlib import Path


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class OutputNamePolicy:
    """为任务选择目录生成稳定、可移植的初始文件名。"""

    def __init__(self, *, max_stem_length: int = 180):
        if max_stem_length < 1:
            raise ValueError("max_stem_length 必须大于 0")
        self.max_stem_length = max_stem_length

    def make_name(self, index: int, source_name: str, used_names: set[str]) -> str:
        if index < 1:
            raise ValueError("文件序号必须从 1 开始")
        source = Path(str(source_name or "image.png"))
        suffix = source.suffix.casefold() or ".png"
        stem = _INVALID_FILENAME_CHARS.sub("_", source.stem).strip(" .") or "image"
        stem = stem[: self.max_stem_length].rstrip(" .") or "image"
        candidate = f"{index:04d}_{stem}{suffix}"
        counter = 2
        occupied = {name.casefold() for name in used_names}
        while candidate.casefold() in occupied:
            candidate = f"{index:04d}_{stem}_{counter}{suffix}"
            counter += 1
        used_names.add(candidate)
        return candidate
