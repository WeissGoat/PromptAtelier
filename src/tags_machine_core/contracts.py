from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


BackendName = Literal["novelai", "comfyui", "sd"]
ComposerName = Literal["script", "agent", "legacy"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PromptText(BaseModel):
    positive: str
    negative: str = ""


class PromptCompositionMeta(BaseModel):
    character_scope: str | None = None
    included_character_sections: list[str] = Field(default_factory=list)
    suppressed_character_sections: list[str] = Field(default_factory=list)


class PromptNodeRef(BaseModel):
    role: str
    id: str
    kind: str
    ref: str
    index: int = 0
    content_hash: str | None = None


class PromptAgentMeta(BaseModel):
    task_schema: str | None = None
    agent_model: str | None = None
    instructions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class PromptMeta(BaseModel):
    composer_type: ComposerName = "script"
    composer_version: str = "v1"
    composition: PromptCompositionMeta = Field(default_factory=PromptCompositionMeta)
    nodes: list[PromptNodeRef] = Field(default_factory=list)
    agent: PromptAgentMeta | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class CacheMeta(BaseModel):
    cacheable: bool = True
    cache_key: str | None = None
    cache_hit: bool = False


class PromptBundle(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.prompt-bundle/v2", alias="schema")
    prompt: PromptText
    meta: PromptMeta = Field(default_factory=PromptMeta)
    cache: CacheMeta = Field(default_factory=CacheMeta)
    created_at: str = Field(default_factory=utc_now_iso)


class RenderSize(BaseModel):
    width: int = 1024
    height: int = 1024


class RenderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.render-request/v1", alias="schema")
    backend: BackendName
    prompt: str
    negative_prompt: str = ""
    model: str | None = None
    seed: int | None = None
    size: RenderSize = Field(default_factory=RenderSize)
    params: dict[str, Any] = Field(default_factory=dict)
    artist_payload: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class GeneratedImage(BaseModel):
    path: Path
    filename: str
    meta: dict[str, Any] = Field(default_factory=dict)


class GenerationResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.generation-result/v1", alias="schema")
    backend: BackendName
    images: list[GeneratedImage] = Field(default_factory=list)
    request_body: dict[str, Any] = Field(default_factory=dict)
    png_info: dict[str, Any] = Field(default_factory=dict)
    cache_hit: bool = False
    created_at: str = Field(default_factory=utc_now_iso)
