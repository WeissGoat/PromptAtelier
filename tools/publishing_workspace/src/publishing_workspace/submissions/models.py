from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ..models import utc_now_iso

SelectionName = Literal["all", "post", "cover"]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SubmissionRevisionConflictError(RuntimeError):
    """投稿 revision 发生冲突。"""


class Submission(BaseModel):
    """Submission 数据模型，对应 submission.yaml。"""

    model_config = ConfigDict(populate_by_name=True)

    schema_id: Literal["publishing-workspace.submission/v1"] = Field(
        default="publishing-workspace.submission/v1",
        alias="schema",
    )
    submission_id: NonEmptyText
    task_id: NonEmptyText
    title: NonEmptyText
    revision: int = Field(default=1, ge=1)
    source_import_id: str | None = None
    sets: dict[SelectionName, list[NonEmptyText]]
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    last_export: dict[str, Any] | None = None

    @field_validator("source_import_id", mode="before")
    @classmethod
    def normalize_source_import_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    @model_validator(mode="after")
    def validate_and_normalize(self) -> "Submission":
        if self.submission_id != self.task_id:
            raise ValueError("submission_id 与 task_id 必须一致")

        allowed_keys: set[str] = {"all", "post", "cover"}
        unknown_keys = set(self.sets.keys()) - allowed_keys
        if unknown_keys:
            raise ValueError(f"不支持的选择集合名称：{sorted(unknown_keys)}")

        normalized_sets: dict[str, list[str]] = {
            "all": [],
            "post": [],
            "cover": [],
        }

        for name in ("all", "post", "cover"):
            raw_list = self.sets.get(name, [])  # type: ignore[call-overload]
            seen: set[str] = set()
            deduped: list[str] = []
            for item in raw_list:
                text = str(item).strip()
                if text and text not in seen:
                    seen.add(text)
                    deduped.append(text)
            normalized_sets[name] = deduped

        # 自动补齐 post 与 cover
        if not normalized_sets["post"] and normalized_sets["all"]:
            normalized_sets["post"] = list(normalized_sets["all"])
        if not normalized_sets["cover"] and normalized_sets["post"]:
            normalized_sets["cover"] = [normalized_sets["post"][0]]

        self.sets = normalized_sets  # type: ignore[assignment]
        return self


class SubmissionDetail(Submission):
    """投稿详情，包含用于 UI/API 展示的告警与未解析文件信息（不写入 submission.yaml）。"""

    warnings: list[str] = Field(default_factory=list)
    unresolved_files: list[str] = Field(default_factory=list)


class SubmissionScheduleRef(BaseModel):
    """计划排期引用。"""

    plan_id: NonEmptyText
    entry_id: NonEmptyText
    scheduled_at: str


class SubmissionSummary(BaseModel):
    """投稿摘要，用于列表展示。"""

    submission_id: NonEmptyText
    task_id: NonEmptyText
    title: NonEmptyText
    counts: dict[SelectionName, int]
    updated_at: str
    scheduled_entries: list[SubmissionScheduleRef] = Field(default_factory=list)
    last_export: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
