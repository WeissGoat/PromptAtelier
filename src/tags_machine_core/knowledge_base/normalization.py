from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .models import ActionClassification, CatalogWarning, NormalizedActionMeta

ENUM_VALUES = {
    "phase": {"start", "pre", "core", "climax", "post"},
    "species": {"human", "human_xeno", "human_tentacle"},
    "cast": {
        "solo",
        "1boy1girl",
        "1boy2girls",
        "1boy3girls",
        "2girls",
        "3girls",
        "multi_boys1girl",
        "multi_boys2girls",
        "multi_boys3girls",
        "multi_boys_multi_girls",
    },
    "domain": {"sex", "body", "foot", "mouth", "breast", "crotch", "yuri", "sfw"},
    "tone": {"normal", "forced", "affectionate"},
    "clothing": {"clothed", "nude", "specific_outfit"},
}

CHARACTER_SCOPES = {
    "default",
    "full_body",
    "upper_body",
    "lower_body",
    "portrait",
    "face_detail",
    "hand_detail",
    "foot_detail",
    "object_focus",
}


def normalize_classification(
    raw: object,
    *,
    ref: str,
) -> tuple[ActionClassification, list[CatalogWarning]]:
    warnings: list[CatalogWarning] = []
    if raw is None:
        return ActionClassification(), warnings
    if not isinstance(raw, dict):
        warnings.append(_warning(ref, "classify.yaml", "schema_mismatch", "classify.yaml 必须是 mapping"))
        return ActionClassification(), warnings

    scalar_values = {
        field: _normalize_scalar(raw.get(field), field, ref, "classify.yaml", warnings)
        for field in ("phase", "species", "cast", "tone", "clothing")
    }
    list_values = {
        field: _normalize_string_list(raw.get(field), field, ref, "classify.yaml", warnings)
        for field in ("domain", "pose", "environment", "flags")
    }
    subtype = _normalize_subtype(raw.get("subtype"), ref, warnings)

    for field, value in scalar_values.items():
        if value is not None:
            _validate_enum(field, value, ref, warnings)
    for value in list_values["domain"]:
        _validate_enum("domain", value, ref, warnings)
    domain_keys = {normalize_search_text(value) for value in list_values["domain"]}
    for key in subtype:
        if normalize_search_text(key) not in domain_keys:
            warnings.append(
                _warning(
                    ref,
                    "classify.yaml",
                    "subtype_domain_mismatch",
                    f"subtype key {key!r} 不在 domain 中",
                    {"subtype": key, "domain": list_values["domain"]},
                )
            )

    return ActionClassification(**scalar_values, **list_values, subtype=subtype), warnings


def normalize_meta(
    raw: object,
    *,
    ref: str,
) -> tuple[NormalizedActionMeta, list[CatalogWarning]]:
    warnings: list[CatalogWarning] = []
    if raw is None:
        return NormalizedActionMeta(), warnings
    if not isinstance(raw, dict):
        warnings.append(_warning(ref, "meta.yaml", "schema_mismatch", "meta.yaml 必须是 mapping"))
        return NormalizedActionMeta(), warnings

    tags = raw.get("tags")
    action_value: object = None
    if tags is None:
        action_value = None
    elif isinstance(tags, dict):
        action_value = tags.get("action")
    else:
        warnings.append(
            _warning(ref, "meta.yaml", "unsupported_prompt_shape", "tags 必须是 mapping")
        )

    positive_raw = _normalize_prompt_fragments(
        action_value,
        ref=ref,
        file="meta.yaml",
        field="tags.action",
        warnings=warnings,
    )
    negative_raw = _normalize_prompt_fragments(
        raw.get("negative_prompt"),
        ref=ref,
        file="meta.yaml",
        field="negative_prompt",
        warnings=warnings,
    )
    positive_terms = split_prompt_terms(positive_raw)
    negative_terms = split_prompt_terms(negative_raw)
    scope = _clean_scalar(raw.get("character_scope"))
    if scope and scope not in CHARACTER_SCOPES:
        warnings.append(
            _warning(
                ref,
                "meta.yaml",
                "invalid_enum",
                f"未知 character_scope: {scope!r}",
                {"field": "character_scope", "value": scope},
            )
        )
    clothing = raw.get("clothing")
    clothing_state = _clean_scalar(clothing.get("state")) if isinstance(clothing, dict) else None
    return NormalizedActionMeta(
        schema_id=_clean_scalar(raw.get("schema")),
        kind=_clean_scalar(raw.get("kind")),
        id=_clean_scalar(raw.get("id")),
        name=_clean_scalar(raw.get("name")),
        description=_clean_scalar(raw.get("description")),
        character_scope=scope,
        positive_terms=positive_terms,
        positive_raw=positive_raw,
        negative_terms=negative_terms,
        negative_raw=negative_raw,
        clothing_state=clothing_state,
    ), warnings


def normalize_search_text(value: object) -> str:
    text = str(value or "").casefold().replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def split_prompt_terms(fragments: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        for raw_term in fragment.split(","):
            term = raw_term.strip()
            key = normalize_search_text(term)
            if term and key not in seen:
                terms.append(term)
                seen.add(key)
    return terms


def stable_json_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_scalar(
    value: object,
    field: str,
    ref: str,
    file: str,
    warnings: list[CatalogWarning],
) -> str | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return _clean_scalar(value)
    warnings.append(
        _warning(
            ref,
            file,
            "schema_mismatch",
            f"{field} 必须是标量",
            {"field": field, "type": type(value).__name__},
        )
    )
    return None


def _normalize_string_list(
    value: object,
    field: str,
    ref: str,
    file: str,
    warnings: list[CatalogWarning],
) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, (dict, list)):
            warnings.append(
                _warning(
                    ref,
                    file,
                    "schema_mismatch",
                    f"{field} 只能包含标量",
                    {"field": field, "type": type(item).__name__},
                )
            )
            continue
        text = _clean_scalar(item)
        key = normalize_search_text(text)
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result


def _normalize_subtype(
    value: object,
    ref: str,
    warnings: list[CatalogWarning],
) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        warnings.append(_warning(ref, "classify.yaml", "schema_mismatch", "subtype 必须是 mapping"))
        return {}
    result: dict[str, list[str]] = {}
    for raw_key, raw_values in value.items():
        key = _clean_scalar(raw_key)
        if not key:
            continue
        result[key] = _normalize_string_list(
            raw_values,
            f"subtype.{key}",
            ref,
            "classify.yaml",
            warnings,
        )
    return result


def _normalize_prompt_fragments(
    value: object,
    *,
    ref: str,
    file: str,
    field: str,
    warnings: list[CatalogWarning],
) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, (str, int, float, bool)):
                text = str(item).strip()
                if text:
                    result.append(text)
            else:
                warnings.append(
                    _warning(
                        ref,
                        file,
                        "unsupported_prompt_shape",
                        f"{field} 包含不支持的值",
                        {"field": field, "type": type(item).__name__},
                    )
                )
        return result
    warnings.append(
        _warning(
            ref,
            file,
            "unsupported_prompt_shape",
            f"{field} 必须是字符串、列表或空值",
            {"field": field, "type": type(value).__name__},
        )
    )
    return []


def _validate_enum(
    field: str,
    value: str,
    ref: str,
    warnings: list[CatalogWarning],
) -> None:
    if normalize_search_text(value).replace(" ", "_") not in ENUM_VALUES[field]:
        warnings.append(
            _warning(
                ref,
                "classify.yaml",
                "invalid_enum",
                f"{field} 包含未知值: {value!r}",
                {"field": field, "value": value},
            )
        )


def _clean_scalar(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _warning(
    ref: str,
    file: str | None,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> CatalogWarning:
    return CatalogWarning(
        ref=ref,
        file=file,
        code=code,
        message=message,
        details=details or {},
    )
