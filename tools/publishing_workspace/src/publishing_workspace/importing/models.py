from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..models import utc_now_iso


ImportMode = Literal["import", "refresh", "retry_problems", "legacy"]
ImportRunStatus = Literal[
    "created",
    "scanning",
    "planned",
    "running",
    "completed",
    "completed_with_errors",
    "interrupted",
    "failed",
]
PipelineStage = Literal[
    "input",
    "planning",
    "execution",
    "classification",
    "export",
    "completed",
]
ImportDecision = Literal[
    "pending",
    "reuse_path",
    "parse",
    "missing_path",
    "empty_file",
    "hold_problem",
    "legacy",
]
ImportItemStatus = Literal[
    "pending",
    "planned",
    "processing",
    "reused_path",
    "reused_content",
    "parsed_new",
    "missing",
    "failed",
    "held_problem",
    "legacy",
]


class ImportCounters(BaseModel):
    total_items: int = 0
    planned_items: int = 0
    processed_items: int = 0
    reused_path_items: int = 0
    reused_content_items: int = 0
    parsed_new_items: int = 0
    missing_items: int = 0
    failed_items: int = 0
    held_problem_items: int = 0


class ImportRunRecord(BaseModel):
    import_id: str
    source_type: str
    source_ref: str
    source_fingerprint: str | None = None
    mode: ImportMode
    strict: bool = False
    status: ImportRunStatus
    pipeline_stage: PipelineStage
    counters: ImportCounters = Field(default_factory=ImportCounters)
    warnings: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    created_at: str
    started_at: str | None = None
    updated_at: str
    completed_at: str | None = None


class ImportItemRecord(BaseModel):
    import_id: str
    source_order: int
    source_path: str
    resolved_path: str | None
    display_name: str
    observed_size: int | None = None
    observed_modified_ns: int | None = None
    decision: ImportDecision
    status: ImportItemStatus
    attempts: int = 0
    asset_id: str | None = None
    problem_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    @property
    def path(self) -> Path | None:
        return Path(self.resolved_path) if self.resolved_path else None


class ImportRunSummary(BaseModel):
    run_id: str
    status: ImportRunStatus
    pipeline_stage: PipelineStage
    source_type: str
    source_ref: str
    total_items: int
    planned_items: int
    processed_items: int
    reused_path_items: int
    reused_content_items: int
    parsed_new_items: int
    missing_items: int
    failed_items: int
    held_problem_items: int
    unique_assets: int
    open_problems: int
    reader_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    snapshot_path: str | None = None
