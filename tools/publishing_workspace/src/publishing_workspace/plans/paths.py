from __future__ import annotations

import re
from pathlib import Path

from ..config import WorkspacePaths


_MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class PlanPaths:
    def __init__(self, workspace: WorkspacePaths, month: str):
        if not _MONTH_PATTERN.fullmatch(month):
            raise ValueError("month 必须使用 YYYY-MM 格式")
        self.workspace = workspace
        self.month = month
        self.plan_root = workspace.plans / month
        self.plan_yaml = self.plan_root / "plan.yaml"
        self.executions_dir = self.plan_root / "executions"

    @classmethod
    def from_workspace(cls, workspace: WorkspacePaths, month: str) -> "PlanPaths":
        return cls(workspace, str(month).strip())

    def ensure_layout(self) -> None:
        self.plan_root.mkdir(parents=True, exist_ok=True)
        self.executions_dir.mkdir(parents=True, exist_ok=True)

    def execution_path(self, execution_id: str) -> Path:
        normalized = str(execution_id).strip()
        if not normalized or Path(normalized).name != normalized:
            raise ValueError("execution_id 必须是单级文件名")
        return self.executions_dir / f"{normalized}.json"
