from __future__ import annotations

import re
from pathlib import Path

from ..config import WorkspacePaths


_TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


class TaskPaths:
    def __init__(self, workspace: WorkspacePaths, task_id: str):
        self.workspace = workspace
        self.task_id = _validate_task_id(task_id)
        self.task_root = workspace.tasks / self.task_id
        self.task_yaml = self.task_root / "task.yaml"
        self.selection_root = self.task_root / "selection"
        self.history_dir = self.selection_root / "history"
        self.selection_dirs = {
            name: self.selection_root / name
            for name in ("all", "post", "cover")
        }
        self.candidates_snapshot = self.selection_root / "candidates.snapshot.json"
        self.candidates_playlist = self.selection_root / "candidates.nvpls"
        self.builds_root = self.task_root / "builds"

    @classmethod
    def from_workspace(cls, workspace: WorkspacePaths, task_id: str) -> "TaskPaths":
        return cls(workspace, task_id)

    def ensure_layout(self) -> None:
        self.task_root.mkdir(parents=True, exist_ok=True)
        self.selection_root.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.builds_root.mkdir(parents=True, exist_ok=True)
        for path in self.selection_dirs.values():
            path.mkdir(parents=True, exist_ok=True)


def _validate_task_id(value: str) -> str:
    text = str(value or "").strip()
    if not text or not _TASK_ID_PATTERN.fullmatch(text):
        raise ValueError(
            "task_id 必须是只包含字母、数字、下划线和连字符的单级目录名"
        )
    return text
