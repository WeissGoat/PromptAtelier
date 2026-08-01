from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..tasks.models import SelectionName


class WarningRecord(BaseModel):
    code: str
    message: str
    selection: SelectionName | None = None
    filename: str | None = None


class BuildManifest(BaseModel):
    schema: Literal["publishing-workspace.build/v1"] = (
        "publishing-workspace.build/v1"
    )
    build_id: str
    task_id: str
    status: Literal["success", "failed"]
    processing_profile: str
    selection: dict[SelectionName, int]
    outputs: dict[SelectionName, int]
    processing_result: dict[str, int]
    warnings: list[WarningRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class BuildResult(BaseModel):
    build_id: str
    build_root: Path
    manifest_path: Path
    output_paths: dict[SelectionName, Path]
    archive_paths: dict[SelectionName, Path]
    selection: dict[SelectionName, int]
