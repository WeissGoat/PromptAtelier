from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..tasks.models import SelectionName


class WarningRecord(BaseModel):
    code: str
    message: str
    selection: SelectionName | None = None
    filename: str | None = None


class BuildManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.build/v1"] = Field(
        default="publishing-workspace.build/v1",
        alias="schema",
    )
    build_id: str
    task_id: str
    status: Literal["success", "failed"]
    processing_profile: str
    selection: dict[str, int]
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
    selection: dict[str, int]
