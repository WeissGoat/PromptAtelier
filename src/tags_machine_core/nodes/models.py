from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


NodeKind = Literal["character", "action", "artist", "background", "vibe", "story", "unknown"]


class LegacyNodeMeta(BaseModel):
    source_file: str | None = None
    raw_lines: list[str] = Field(default_factory=list)
    raw_sections: dict[str, list[str]] = Field(default_factory=dict)


class NodeDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.node/v1", alias="schema")
    kind: NodeKind = "unknown"
    id: str
    name: str | None = None
    path: Path | None = None
    tags: dict[str, list[str]] = Field(default_factory=dict)
    generation: dict[str, Any] = Field(default_factory=dict)
    renderers: dict[str, Any] = Field(default_factory=dict)
    agent: dict[str, Any] = Field(default_factory=dict)
    legacy: LegacyNodeMeta = Field(default_factory=LegacyNodeMeta)

    def all_tags(self) -> list[str]:
        items: list[str] = []
        for values in self.tags.values():
            items.extend(values)
        return items
