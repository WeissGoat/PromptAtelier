from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import utc_now_iso


SelectionName = Literal["all", "post", "cover"]
ImportMode = Literal["replace", "append"]


class OperationConfig(BaseModel):
    enabled: bool = True
    version: str = "1"
    adapter: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ProcessingConfig(BaseModel):
    profile: str = "pixiv_default"
    operations: dict[str, OperationConfig] = Field(
        default_factory=lambda: {
            "strip_metadata": OperationConfig(enabled=True),
            "mosaic": OperationConfig(enabled=False),
        }
    )


class DirectoryOutputConfig(BaseModel):
    enabled: Literal[True] = True


class ZipOutputConfig(BaseModel):
    enabled: bool = False
    targets: list[SelectionName] = Field(
        default_factory=lambda: ["all", "post", "cover"]
    )

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, value: list[SelectionName]) -> list[SelectionName]:
        if len(set(value)) != len(value):
            raise ValueError("packages.zip.targets 不能重复")
        return value


class PackageConfig(BaseModel):
    directories: DirectoryOutputConfig = Field(default_factory=DirectoryOutputConfig)
    zip: ZipOutputConfig = Field(default_factory=ZipOutputConfig)


class TaskConfig(BaseModel):
    version: Literal[1] = 1
    task_id: str
    title: str
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    packages: PackageConfig = Field(default_factory=PackageConfig)

    @field_validator("task_id", "title")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("task_id/title 不能为空")
        return text


class SelectionImportHistory(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.selection-import/v1"] = Field(
        default="publishing-workspace.selection-import/v1",
        alias="schema",
    )
    """对外序列化为 schema，避免覆盖 Pydantic 的 BaseModel.schema 方法。"""

    history_id: str
    selection: SelectionName
    mode: ImportMode
    source_type: str
    source_ref: str
    imported_at: str = Field(default_factory=utc_now_iso)
    source_items: list[dict[str, Any]] = Field(default_factory=list)
    materialized_files: list[str] = Field(default_factory=list)
    skipped_duplicates: int = 0
    warnings: list[str] = Field(default_factory=list)


class MaterializeResult(BaseModel):
    materialized_files: list[str] = Field(default_factory=list)
    skipped_duplicates: int = 0
    warnings: list[str] = Field(default_factory=list)


class SelectionFile(BaseModel):
    selection: SelectionName
    filename: str
    relative_path: str
    absolute_path: str
    content_sha256: str
    asset_id: str | None = None


class SelectionSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.selection-snapshot/v1"] = Field(
        default="publishing-workspace.selection-snapshot/v1",
        alias="schema",
    )
    build_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    selections: dict[SelectionName, list[SelectionFile]]
