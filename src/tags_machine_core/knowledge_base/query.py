from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from .models import (
    SEARCH_RESULT_SCHEMA,
    ActionCatalogItem,
    CatalogWarning,
    LoadedCatalog,
)
from .normalization import normalize_search_text


class ActionSearchFilters(BaseModel):
    source: list[str] = Field(default_factory=list)
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
    character_scope: list[str] = Field(default_factory=list)
    text: str | None = None
    limit: int = 20
    all_sources: bool = False

    @field_validator(
        "source",
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
        "character_scope",
        mode="before",
    )
    @classmethod
    def normalize_filter_values(cls, value: object) -> list[str]:
        if value is None:
            return []
        values = value if isinstance(value, list) else [value]
        result: list[str] = []
        for item in values:
            result.extend(part.strip() for part in str(item).split(",") if part.strip())
        return list(dict.fromkeys(result))

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("search limit must be at least 1")
        return value


def audit_catalog(catalog: LoadedCatalog) -> dict[str, Any]:
    counts = Counter(warning.code for warning in catalog.warnings)
    return {
        "schema": "tags-machine-core.kb-audit-result/v1",
        "catalog_hash": catalog.manifest.catalog_hash,
        "warning_count": len(catalog.warnings),
        "warning_counts": dict(sorted(counts.items())),
        "warnings": [warning.model_dump(mode="json") for warning in catalog.warnings],
    }


def build_facets(catalog: LoadedCatalog) -> dict[str, Any]:
    facets: dict[str, Counter[str]] = defaultdict(Counter)
    for item in _canonical_items(catalog.items):
        _count(facets["source"], item.source.group)
        _count(facets["phase"], item.classification.phase)
        _count(facets["species"], item.classification.species)
        _count(facets["cast"], item.classification.cast)
        for value in item.classification.domain:
            _count(facets["domain"], value)
        for key, values in item.classification.subtype.items():
            _count(facets["subtype"], key)
            for value in values:
                _count(facets["subtype"], value)
        for value in item.classification.pose:
            _count(facets["pose"], value)
        for value in item.classification.environment:
            _count(facets["environment"], value)
        _count(facets["tone"], item.classification.tone)
        for value in item.classification.flags:
            _count(facets["flags"], value)
        _count(facets["clothing"], item.classification.clothing)
        _count(facets["character_scope"], item.action.character_scope)
    ordered_names = (
        "source",
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
        "character_scope",
    )
    return {
        "schema": "tags-machine-core.action-facets/v1",
        "catalog_hash": catalog.manifest.catalog_hash,
        "record_count": len(_canonical_items(catalog.items)),
        "facets": {
            name: dict(sorted(facets[name].items(), key=lambda pair: (-pair[1], pair[0])))
            for name in ordered_names
        },
    }


def search_actions(catalog: LoadedCatalog, filters: ActionSearchFilters) -> dict[str, Any]:
    candidates = catalog.items if filters.all_sources else _canonical_items(catalog.items)
    matches: list[tuple[int, ActionCatalogItem]] = []
    for item in candidates:
        if not _matches_filters(item, filters):
            continue
        score = _text_score(item, filters.text)
        if filters.text and score == 0:
            continue
        matches.append((score, item))
    matches.sort(key=lambda pair: (-pair[0], pair[1].ref))
    total = len(matches)
    results = [
        _search_summary(item, score)
        for score, item in matches[: filters.limit]
    ]
    return {
        "schema": SEARCH_RESULT_SCHEMA,
        "catalog_hash": catalog.manifest.catalog_hash,
        "total": total,
        "limit": filters.limit,
        "results": results,
    }


def show_action(catalog: LoadedCatalog, ref: str) -> dict[str, Any]:
    item = next((candidate for candidate in catalog.items if candidate.ref == ref), None)
    if item is None:
        raise KeyError(f"action ref not found: {ref}")
    action_root = Path(catalog.manifest.action_root).resolve()
    source_warnings = [warning for warning in catalog.warnings if warning.ref == ref]
    dynamic_warnings: list[CatalogWarning] = []
    classify = _read_yaml_source(
        action_root,
        item.files.classify_path,
        ref,
        "classify.yaml",
        dynamic_warnings,
    )
    meta = _read_yaml_source(
        action_root,
        item.files.meta_path,
        ref,
        "meta.yaml",
        dynamic_warnings,
    )
    tags_text = _read_text_source(
        action_root,
        item.files.tags_path,
        ref,
        "tags.txt",
        dynamic_warnings,
    )
    return {
        "schema": "tags-machine-core.action-show-result/v1",
        "catalog_hash": catalog.manifest.catalog_hash,
        "item": item.model_dump(by_alias=True, mode="json"),
        "classify": classify if isinstance(classify, dict) else {},
        "meta": meta if isinstance(meta, dict) else {},
        "tags_text": tags_text,
        "warnings": [
            warning.model_dump(mode="json") for warning in [*source_warnings, *dynamic_warnings]
        ],
    }


def _matches_filters(item: ActionCatalogItem, filters: ActionSearchFilters) -> bool:
    subtype_values = list(item.classification.subtype)
    for values in item.classification.subtype.values():
        subtype_values.extend(values)
    values_by_field = {
        "source": [item.source.group, item.source.root_id],
        "phase": [item.classification.phase],
        "species": [item.classification.species],
        "cast": [item.classification.cast],
        "domain": item.classification.domain,
        "subtype": subtype_values,
        "pose": item.classification.pose,
        "environment": item.classification.environment,
        "tone": [item.classification.tone],
        "flags": item.classification.flags,
        "clothing": [item.classification.clothing],
        "character_scope": [item.action.character_scope],
    }
    for field, item_values in values_by_field.items():
        requested = getattr(filters, field)
        if requested and not _has_any(item_values, requested):
            return False
    return True


def _text_score(item: ActionCatalogItem, text: str | None) -> int:
    if not text:
        return 0
    needle = normalize_search_text(text)
    if not needle:
        return 0
    score = 0
    for value, weight in (
        (item.id, 8),
        (item.action.name, 8),
        (item.action.description, 4),
    ):
        if needle in normalize_search_text(value):
            score += weight
    for term in item.action.positive_terms:
        if needle in normalize_search_text(term):
            score += 2
    return score


def _search_summary(item: ActionCatalogItem, score: int) -> dict[str, Any]:
    return {
        "score": score,
        "ref": item.ref,
        "id": item.id,
        "name": item.action.name,
        "description": item.action.description,
        "source": item.source.model_dump(mode="json"),
        "classification": item.classification.model_dump(mode="json"),
        "character_scope": item.action.character_scope,
        "alias_group": item.alias_group,
        "canonical_ref": item.canonical_ref,
        "aliases": item.aliases,
        "warnings": item.warnings,
    }


def _has_any(values: list[object], requested: list[str]) -> bool:
    normalized_values = {normalize_search_text(value) for value in values if value is not None}
    return any(normalize_search_text(value) in normalized_values for value in requested)


def _canonical_items(items: list[ActionCatalogItem]) -> list[ActionCatalogItem]:
    return [item for item in items if item.ref == item.canonical_ref]


def _count(counter: Counter[str], value: str | None) -> None:
    if value:
        counter[value] += 1


def _read_yaml_source(
    action_root: Path,
    relative_path: str | None,
    ref: str,
    filename: str,
    warnings: list[CatalogWarning],
) -> object:
    text = _read_text_source(action_root, relative_path, ref, filename, warnings)
    if text is None:
        return {}
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        warnings.append(
            CatalogWarning(
                ref=ref,
                file=filename,
                code="parse_error",
                message=f"show 时解析 {filename} 失败: {exc}",
            )
        )
        return {}


def _read_text_source(
    action_root: Path,
    relative_path: str | None,
    ref: str,
    filename: str,
    warnings: list[CatalogWarning],
) -> str | None:
    if not relative_path:
        return None
    path = (action_root / relative_path).resolve()
    try:
        path.relative_to(action_root)
    except ValueError as exc:
        raise ValueError(f"catalog source path escapes action_root: {relative_path}") from exc
    if not path.is_file():
        warnings.append(
            CatalogWarning(
                ref=ref,
                file=filename,
                code="source_missing",
                message=f"Catalog 导入后源文件已不存在: {relative_path}",
            )
        )
        return None
    return path.read_text(encoding="utf-8", errors="replace")
