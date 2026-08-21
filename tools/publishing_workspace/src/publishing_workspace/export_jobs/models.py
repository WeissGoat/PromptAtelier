from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..tasks.models import SelectionName

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ExportJob(BaseModel):
    """导出任务模型。"""

    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.export-job/v1"] = Field(
        default="publishing-workspace.export-job/v1",
        alias="schema",
    )
    job_id: NonEmptyText
    task_id: NonEmptyText
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    phase: Literal["validate", "process", "archive", "finalize"] | None = None
    processed: int = 0
    total: int = 0
    percent: int = 0
    current_selection: SelectionName | None = None
    current_filename: str | None = None
    build_id: str | None = None
    output_dir: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class ExportOutputNotFoundError(FileNotFoundError):
    """导出目录不存在。"""


class ExportOutputOpenError(RuntimeError):
    """系统无法直接打开导出目录（例如非桌面环境）。"""

    def __init__(self, message: str, *, output_dir: str):
        super().__init__(message)
        self.output_dir = output_dir
