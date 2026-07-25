from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


CLASSIFY_FIELDS = (
    "phase",
    "species",
    "cast",
    "domain",
    "subtype",
    "pose",
    "environment",
    "tone",
    "flags",
    "clothing",
)


class NodePoolSource(BaseModel):
    type: Literal["folder", "collection", "glob"]
    value: str
    recursive: bool = False
    include_names: list[str] = Field(default_factory=list)
    exclude_names: list[str] = Field(default_factory=list)

    @field_validator("value")
    @classmethod
    def _value_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("node pool source value must not be empty")
        return text


class ClassifyFilter(BaseModel):
    phase: list[str] = Field(default_factory=list)
    species: list[str] = Field(default_factory=list)
    cast: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    subtype: list[str] = Field(default_factory=list)
    pose: list[str] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    tone: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    clothing: list[str] = Field(default_factory=list)

    @field_validator("*", mode="before")
    @classmethod
    def _normalize_values(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        items = value if isinstance(value, list) else [value]
        return list(dict.fromkeys(str(item).strip().lower() for item in items if str(item).strip()))

    def enabled(self) -> bool:
        return any(getattr(self, field) for field in CLASSIFY_FIELDS)


class NodePoolFilters(BaseModel):
    classify: ClassifyFilter = Field(default_factory=ClassifyFilter)


class NodePoolSpec(BaseModel):
    source: NodePoolSource
    filters: NodePoolFilters = Field(default_factory=NodePoolFilters)


class CandidateNode(BaseModel):
    role: str
    ref: str
    name: str
    relative: str | None = None


class NodePoolStats(BaseModel):
    raw_total: int = 0
    total: int = 0
    missing_classify: int = 0
    invalid_classify: int = 0
    classify_mismatch: int = 0
    invalid_node: int = 0


class NodePoolScanResult(BaseModel):
    candidates: list[CandidateNode] = Field(default_factory=list)
    stats: NodePoolStats = Field(default_factory=NodePoolStats)
    facets: dict[str, list[str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class SampledNode(BaseModel):
    candidate: CandidateNode
    node: dict[str, Any]
    draw_index: int
    deck_cycle: int


class NodePoolSampleResult(BaseModel):
    items: list[SampledNode] = Field(default_factory=list)
    stats: NodePoolStats = Field(default_factory=NodePoolStats)
