"""CLI 分段读取：`--frames f01-f30`、`--members 1-20` 这类范围写法。"""

from __future__ import annotations

from typing import Any


def _parts(spec: str) -> list[str]:
    return [part.strip() for part in spec.replace("，", ",").split(",") if part.strip()]


def select_indexes(spec: str | None, total: int) -> set[int]:
    """`1-20,25,30-` → 序号集合（从 1 开始，含两端）；`30-` 表示到最后一个。"""
    if not spec:
        return set(range(1, total + 1))
    result: set[int] = set()
    for part in _parts(spec):
        start, dash, end = part.partition("-")
        try:
            low = int(start) if start else 1
            high = (int(end) if end else total) if dash else low
        except ValueError as exc:
            raise ValueError(f"范围写法不对：{part}（例：1-20、3,5,8-10）") from exc
        if low > high:
            low, high = high, low
        result.update(range(max(low, 1), min(high, total) + 1))
    return result


def select_frames(frames: list[dict[str, Any]], spec: str | None) -> list[dict[str, Any]]:
    """按帧 id 选帧：`f01-f30` 取两帧之间（按契约里的顺序，含插入的 f02b）；也可以逗号列出。"""
    if not spec:
        return frames
    position = {frame["id"]: index for index, frame in enumerate(frames)}
    wanted: set[int] = set()
    for part in _parts(spec):
        start, dash, end = part.partition("-")
        if not dash:
            if start not in position:
                raise ValueError(f"没有帧 {start}")
            wanted.add(position[start])
            continue
        low = position.get(start, 0) if start else 0
        high = position.get(end, len(frames) - 1) if end else len(frames) - 1
        for name in (start, end):
            if name and name not in position:
                raise ValueError(f"没有帧 {name}")
        if low > high:
            low, high = high, low
        wanted.update(range(low, high + 1))
    return [frame for index, frame in enumerate(frames) if index in wanted]
