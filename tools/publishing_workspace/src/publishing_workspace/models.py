from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImportedItem(BaseModel):
    source_path: str
    resolved_path: str | None = None
    source_type: str
    source_ref: str
    source_order: int
    display_name: str
    warnings: list[str] = Field(default_factory=list)

    @field_validator("source_path", "source_ref", mode="before")
    @classmethod
    def normalize_required_path(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("路径不能为空")
        return text


class SelectionSet(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    source_type: str
    source_ref: str
    items: list[ImportedItem] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    warnings: list[str] = Field(default_factory=list)


class ImageNodeRef(BaseModel):
    role: str
    id: str | None = None
    ref: str | None = None
    index: int = 0

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("节点 role 不能为空")
        return text


class ImageNodeInfo(BaseModel):
    format: Literal["core", "legacy", "unknown"] = "unknown"
    reader: str = "unknown"
    nodes: list[ImageNodeRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def values_for(self, role: str) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for node in self.nodes:
            if node.role != role:
                continue
            value = (node.id or _name_from_ref(node.ref) or "").strip()
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                values.append(value)
        return values


class AssetFingerprint(BaseModel):
    size: int
    modified_ns: int
    sha256: str


class AssetImageInfo(BaseModel):
    width: int
    height: int
    format: str


class AssetRecord(BaseModel):
    asset_id: str
    path: str
    fingerprint: AssetFingerprint
    image: AssetImageInfo
    node_info: ImageNodeInfo
    source_order: int = 0
    display_name: str = ""
    warnings: list[str] = Field(default_factory=list)

    def node_values(self, role: str) -> list[str]:
        return self.node_info.values_for(role)


class ViewItem(BaseModel):
    asset_id: str
    source_path: str
    display_name: str
    order: int


class ViewEntry(BaseModel):
    path: list[str]
    items: list[ViewItem] = Field(default_factory=list)

    @property
    def key(self) -> str:
        return "/".join(self.path)


class ExportPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(
        default="publishing-workspace.export-plan/v1",
        alias="schema",
    )
    import_id: str | None = None
    hierarchy: list[str]
    views: list[ViewEntry] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)


class ImportResult(BaseModel):
    import_id: str
    source_type: str
    source_ref: str
    total_items: int
    imported_items: int
    missing_items: int
    failed_items: int
    unique_assets: int
    reader_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    snapshot_path: str


class ExporterResult(BaseModel):
    exporter: str
    written: int = 0
    skipped: int = 0
    removed: int = 0
    output_root: str
    warnings: list[str] = Field(default_factory=list)


class ExportSummary(BaseModel):
    plan_views: int
    results: list[ExporterResult] = Field(default_factory=list)


def _name_from_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    normalized = ref.replace("\\", "/").rstrip("/")
    return Path(normalized).name or None
