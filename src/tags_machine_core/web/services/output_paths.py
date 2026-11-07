"""网页出图的输出目录：前端只给相对目录名（如 `compares/primary_<时间>_<id>`），后端拼到 runtime.output_dir 下。

输出根目录只在配置里写一处，换盘或迁移时前端不用改。
旧前端和旧任务记录里的 `outputs/...` 前缀按输出根目录处理，迁移后照样写到新位置。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any


LEGACY_OUTPUT_PREFIX = "outputs"


def resolve_output_dir(root: str | Path, value: Any) -> str | None:
    """把请求里的 output_dir 换成输出根目录下的绝对路径；没给时返回 None（执行器用默认根目录）。"""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if Path(raw).is_absolute():
        return str(Path(raw))
    parts = PurePosixPath(raw.replace("\\", "/")).parts
    if parts and parts[0] == LEGACY_OUTPUT_PREFIX:
        parts = parts[1:]
    if any(part in {"..", "."} for part in parts):
        raise ValueError(f"output_dir must stay inside the output root: {raw}")
    return str(Path(root).resolve().joinpath(*parts))


def resolve_batch_output_dirs(root: str | Path, batch: dict[str, Any]) -> dict[str, Any]:
    """批量任务：批次目录和每一项的目录都换成绝对路径，任务记录、继续剩余项都按这个位置。"""
    items = []
    for item in batch["items"]:
        generate = dict(item["generate"])
        if "output_dir" in generate:
            generate["output_dir"] = resolve_output_dir(root, generate["output_dir"])
        items.append({**item, "generate": generate})
    return {**batch, "output_dir": resolve_output_dir(root, batch.get("output_dir")), "items": items}
