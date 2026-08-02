from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CATALOG_ITEM_SCHEMA = "tags-machine-core.action-catalog-item/v1"
CATALOG_POINTER_SCHEMA = "tags-machine-core.action-catalog-pointer/v1"
IMPORT_RESULT_SCHEMA = "tags-machine-core.kb-import-result/v1"
SEARCH_RESULT_SCHEMA = "tags-machine-core.action-search-result/v1"


class CatalogWarning(BaseModel):
    ref: str
    file: str | None = None
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ActionClassification(BaseModel):
    phase: str | None = None
    species: str | None = None
    cast: str | None = None
    domain: list[str] = Field(default_factory=list)
    subtype: dict[str, list[str]] = Field(default_factory=dict)
    pose: list[str] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    tone: str | None = None
    flags: list[str] = Field(default_factory=list)
    clothing: str | None = None


class NormalizedActionMeta(BaseModel):
    schema_id: str | None = None
    kind: str | None = None
    id: str | None = None
    name: str | None = None
    description: str | None = None
    character_scope: str | None = None
    positive_terms: list[str] = Field(default_factory=list)
    positive_raw: list[str] = Field(default_factory=list)
    negative_terms: list[str] = Field(default_factory=list)
    negative_raw: list[str] = Field(default_factory=list)
    clothing_state: str | None = None


class CatalogSource(BaseModel):
    root_id: str
    relative_path: str
    group: str


class CatalogFiles(BaseModel):
    tags_path: str | None = None
    classify_path: str | None = None
    meta_path: str | None = None
    tags_hash: str | None = None
    classify_hash: str | None = None
    meta_hash: str | None = None
    content_hash: str


class CatalogActionSummary(BaseModel):
    name: str
    description: str | None = None
    character_scope: str | None = None
    positive_terms: list[str] = Field(default_factory=list)
    negative_terms_count: int = 0
    negative_hash: str


class ActionCatalogItem(BaseModel):
    schema_id: str = Field(default=CATALOG_ITEM_SCHEMA, alias="schema")
    ref: str
    id: str
    kind: Literal["action"] = "action"
    source: CatalogSource
    files: CatalogFiles
    classification: ActionClassification
    action: CatalogActionSummary
    alias_group: str
    canonical_ref: str
    aliases: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class KnowledgeBaseImportResult(BaseModel):
    schema_id: str = Field(default=IMPORT_RESULT_SCHEMA, alias="schema")
    catalog_hash: str
    build_dir: str
    record_count: int
    alias_group_count: int
    warning_count: int
    reused_build: bool

    model_config = ConfigDict(populate_by_name=True)


class CatalogManifest(BaseModel):
    schema_id: str = Field(default="tags-machine-core.action-catalog-manifest/v1", alias="schema")
    catalog_hash: str
    created_at: str
    action_root: str
    config_path: str
    source_roots: list[dict[str, str]]
    record_count: int
    alias_group_count: int
    warning_count: int

    model_config = ConfigDict(populate_by_name=True)


class CatalogPointer(BaseModel):
    schema_id: str = Field(default=CATALOG_POINTER_SCHEMA, alias="schema")
    catalog_hash: str
    build: str

    model_config = ConfigDict(populate_by_name=True)


class LoadedCatalog(BaseModel):
    manifest: CatalogManifest
    items: list[ActionCatalogItem]
    warnings: list[CatalogWarning]
    build_dir: Path

    model_config = ConfigDict(arbitrary_types_allowed=True)
