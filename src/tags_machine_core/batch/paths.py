from __future__ import annotations

from datetime import datetime
from pathlib import Path


def resolve_batch_output_path(
    value: str | Path,
    *,
    now: datetime | None = None,
) -> Path:
    """展开 Batch 输出路径中与本次运行绑定的模板变量。"""

    resolved_now = now or datetime.now()
    return Path(str(value).replace("{date}", resolved_now.strftime("%Y%m%d")))
