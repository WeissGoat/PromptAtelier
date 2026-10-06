"""节点预览图：只看节点目录里直接放的图片（不进子目录、不跟快捷方式）。

1. 先取非生成图（不以 gen_ / blackboard_ 开头）里最早的一张；
2. 没有就取目录里最早的任意一张图；
3. 都没有就没有预览图（前端显示占位）。

"最早"按文件修改时间，同一时间再按文件名。结果按目录 mtime 缓存，目录里增删图片后自动失效。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path


IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
GENERATED_PREFIXES = ("gen_", "blackboard_")


def pick_preview(node_dir: Path) -> Path | None:
    own: list[tuple[int, str, Path]] = []
    generated: list[tuple[int, str, Path]] = []
    try:
        with os.scandir(node_dir) as entries:
            for entry in entries:
                if Path(entry.name).suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                try:
                    if not entry.is_file():
                        continue
                    key = (entry.stat().st_mtime_ns, entry.name, Path(entry.path))
                except OSError:
                    continue
                (generated if entry.name.lower().startswith(GENERATED_PREFIXES) else own).append(key)
    except OSError:
        return None
    pool = own or generated
    return min(pool)[2] if pool else None


class NodePreviewIndex:
    def __init__(self) -> None:
        self._cache: dict[Path, tuple[int, Path | None]] = {}
        self._lock = threading.Lock()

    def preview_for(self, node_dir: Path) -> Path | None:
        try:
            mtime_ns = node_dir.stat().st_mtime_ns
        except OSError:
            return None
        with self._lock:
            cached = self._cache.get(node_dir)
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]
        preview = pick_preview(node_dir)
        with self._lock:
            self._cache[node_dir] = (mtime_ns, preview)
        return preview
