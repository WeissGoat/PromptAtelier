from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


NodeKind = Literal[
    "character",
    "action",
    "artist",
    "style",
    "background",
    "vibe",
    "story",
    "unknown",
]


class LegacyNodeMeta(BaseModel):
    source_file: str | None = None
    raw_lines: list[str] = Field(default_factory=list)
    raw_sections: dict[str, list[str]] = Field(default_factory=dict)


class PromptFragment(BaseModel):
    text: str
    role: str | None = None
    weight: float | None = None
    include_scopes: list[str] = Field(default_factory=list)
    exclude_scopes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("include_scopes", "exclude_scopes", "notes", mode="before")
    @classmethod
    def normalize_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def applies_to(self, body_scope: str | None) -> bool:
        if body_scope and body_scope in self.exclude_scopes:
            return False
        if not self.include_scopes or "*" in self.include_scopes:
            return True
        if not body_scope:
            return False
        return body_scope in self.include_scopes


class NodePrompt(BaseModel):
    positive: list[PromptFragment] = Field(default_factory=list)
    negative: list[PromptFragment] = Field(default_factory=list)

    @field_validator("positive", "negative", mode="before")
    @classmethod
    def normalize_fragments(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, str):
            return [{"text": value}]
        if isinstance(value, list):
            items: list[Any] = []
            for item in value:
                if isinstance(item, str):
                    if item.strip():
                        items.append({"text": item.strip()})
                elif isinstance(item, dict):
                    items.append(item)
            return items
        if isinstance(value, dict):
            return [value]
        return [{"text": str(value)}] if str(value).strip() else []


class NodeDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.node/v1", alias="schema")
    kind: NodeKind = "unknown"
    id: str
    name: str | None = None
    character_id: str | None = None
    variant: str | None = None
    character_scope: str | None = None
    path: Path | None = None
    tags: dict[str, list[str]] = Field(default_factory=dict)
    negative_prompt: list[str] = Field(default_factory=list)
    description: str | None = None
    prompt: NodePrompt = Field(default_factory=NodePrompt)
    generation: dict[str, Any] = Field(default_factory=dict)
    renderers: dict[str, Any] = Field(default_factory=dict)
    agent: dict[str, Any] = Field(default_factory=dict)
    legacy: LegacyNodeMeta = Field(default_factory=LegacyNodeMeta)

    @field_validator("negative_prompt", mode="before")
    @classmethod
    def normalize_negative_prompt(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def all_tags(self) -> list[str]:
        items: list[str] = []
        for values in self.tags.values():
            items.extend(values)
        return items

    def positive_texts(self, body_scope: str | None = None) -> list[str]:
        return [
            fragment.text
            for fragment in self.prompt.positive
            if fragment.applies_to(body_scope)
        ]

    def negative_texts(self, body_scope: str | None = None) -> list[str]:
        return [
            fragment.text
            for fragment in self.prompt.negative
            if fragment.applies_to(body_scope)
        ]

    def source_ref(self) -> str:
        return str(self.path) if self.path else self.id
