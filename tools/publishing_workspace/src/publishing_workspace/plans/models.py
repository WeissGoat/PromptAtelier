from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


SelectionName = Literal["all", "post", "cover"]
PlanStatus = Literal["draft", "locked"]

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TaskContent(BaseModel):
    kind: Literal["task"] = "task"
    task_id: NonEmptyText


class InlineContent(BaseModel):
    kind: Literal["inline_selection"] = "inline_selection"
    source_import_id: str | None = None
    sets: dict[SelectionName, list[NonEmptyText]] = Field(
        default_factory=lambda: {"all": [], "post": [], "cover": []}
    )

    @model_validator(mode="after")
    def normalize_sets(self) -> "InlineContent":
        normalized: dict[str, list[str]] = {"all": [], "post": [], "cover": []}
        for selection_name, asset_ids in self.sets.items():
            if selection_name not in normalized:
                raise ValueError(f"不支持的选择集合：{selection_name}")
            seen: set[str] = set()
            for asset_id in asset_ids:
                value = str(asset_id).strip()
                if value and value not in seen:
                    normalized[selection_name].append(value)
                    seen.add(value)
        self.sets = normalized  # type: ignore[assignment]
        if self.source_import_id is not None:
            self.source_import_id = self.source_import_id.strip() or None
        return self


class ExecutionPolicy(BaseModel):
    build_on_due: bool = True
    notify_on_complete: bool = True
    publish: bool = False


class ScheduleEntry(BaseModel):
    entry_id: NonEmptyText
    scheduled_at: datetime
    title: NonEmptyText
    content: Annotated[TaskContent | InlineContent, Field(discriminator="kind")]
    execution: ExecutionPolicy = Field(default_factory=ExecutionPolicy)

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_at 必须包含时区")
        return value


class MonthlyPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.monthly-plan/v1"] = Field(
        default="publishing-workspace.monthly-plan/v1",
        alias="schema",
    )
    plan_id: NonEmptyText
    month: str
    timezone: str = "Asia/Shanghai"
    status: PlanStatus = "draft"
    default_import_id: str | None = None
    revision: int = Field(default=1, ge=1)
    entries: list[ScheduleEntry] = Field(default_factory=list)

    @field_validator("month")
    @classmethod
    def validate_month(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != 7 or normalized[4] != "-":
            raise ValueError("month 必须使用 YYYY-MM 格式")
        year, month = normalized.split("-")
        if not year.isdigit() or not month.isdigit() or not 1 <= int(month) <= 12:
            raise ValueError("month 必须使用 YYYY-MM 格式")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"不支持的时区：{normalized}") from exc
        return normalized

    @model_validator(mode="after")
    def validate_entries(self) -> "MonthlyPlan":
        entry_ids: set[str] = set()
        timezone = ZoneInfo(self.timezone)
        for entry in self.entries:
            if entry.entry_id in entry_ids:
                raise ValueError(f"entry_id 重复：{entry.entry_id}")
            entry_ids.add(entry.entry_id)
            local_time = entry.scheduled_at.astimezone(timezone)
            if local_time.strftime("%Y-%m") != self.month:
                raise ValueError(
                    f"scheduled_at 不属于计划月份：{entry.entry_id} -> {self.month}"
                )
        if self.default_import_id is not None:
            self.default_import_id = self.default_import_id.strip() or None
        return self


class ExecutionRecord(BaseModel):
    execution_id: NonEmptyText
    entry_id: NonEmptyText
    plan_revision: int = Field(ge=1)
    scheduled_at: datetime
    status: Literal["running", "completed", "failed"]
    build_id: str | None = None
    task_id: str | None = None
    notification_status: Literal["pending", "sent", "failed", "disabled"] = "pending"
    error: str | None = None
    reason: Literal["due", "manual_preview", "retry"] = "due"

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_at 必须包含时区")
        return value
