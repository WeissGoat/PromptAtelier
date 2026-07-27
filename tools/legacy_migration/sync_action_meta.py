"""每天同步动作目录中的 meta.yaml 与 clothing 元数据。"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .fill_action_meta_clothing import fill_action_meta_clothing


LOCK_FILENAME = ".action-meta-sync.lock"


class ActionMetaSyncLockedError(RuntimeError):
    """动作元数据同步任务已经在运行。"""


def sync_action_meta(
    root: Path,
    *,
    write: bool = False,
    backup: bool = False,
    lock: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"root not found: {root}")
    if not root.is_dir():
        raise ValueError(f"root must be a directory: {root}")

    lock_enabled = bool(write and lock)
    with _sync_lock(root, enabled=lock_enabled):
        report = fill_action_meta_clothing(
            root,
            write=write,
            backup=backup,
            ensure_meta=True,
        )

    report["schema"] = "tags-machine-tools.action-meta-sync/v1"
    report["summary"]["lock_enabled"] = lock_enabled
    return report


@contextmanager
def _sync_lock(root: Path, *, enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return

    lock_path = root / LOCK_FILENAME
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(lock_path, flags)
    except FileExistsError as exc:
        detail = lock_path.read_text(encoding="utf-8", errors="replace").strip()
        suffix = f" ({detail})" if detail else ""
        raise ActionMetaSyncLockedError(
            f"action meta sync is already locked: {lock_path}{suffix}"
        ) from exc

    payload = {
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        yield
    finally:
        lock_path.unlink(missing_ok=True)
