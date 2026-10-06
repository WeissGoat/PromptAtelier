from __future__ import annotations

import os
from pathlib import Path


def contained_path(root: str | Path, path: str | Path) -> Path | None:
    """返回 path 在 root 内的可用路径；不在 root 内返回 None。

    先按逻辑路径判断：root 下的目录链接 / Junction 允许指向别处，返回规范化后的逻辑路径。
    返回值始终是 normpath 之后的路径——不能返回原始路径，否则 `link/../x` 这类写法
    会在词法检查通过后，被系统按物理路径解析到 root 之外。
    逻辑判断不通过再回退到解析后的物理路径。
    """
    norm_root = Path(os.path.normpath(root))
    norm_path = Path(os.path.normpath(path))
    try:
        norm_path.relative_to(norm_root)
        return norm_path
    except ValueError:
        pass
    resolved = norm_path.resolve()
    try:
        resolved.relative_to(norm_root.resolve())
    except ValueError:
        return None
    return resolved


def relative_within(root: str | Path, path: str | Path) -> str | None:
    """path 相对 root 的 posix 路径；不在 root 内返回 None。"""
    contained = contained_path(root, path)
    if contained is None:
        return None
    for base in (Path(os.path.normpath(root)), Path(os.path.normpath(root)).resolve()):
        try:
            return contained.relative_to(base).as_posix()
        except ValueError:
            continue
    return None
