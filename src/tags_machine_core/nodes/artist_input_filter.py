from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from tags_machine_core.logging_config import get_logger

from .models import NodeDocument
from .novelai_artist import NovelAIArtist


logger = get_logger(__name__)

ArtistNegativeField = Literal["negative_prompt", "after_negative_prompt"]

_NUMERIC_WEIGHT_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?::(.*)::$")
_SPACE_RE = re.compile(r"\s+")
_UNDERSCORE_RE = re.compile(r"_+")


class ArtistNegativePromptFilterConfig(BaseModel):
    enabled: bool = True
    blocked_tokens: list[str] = Field(default_factory=lambda: ["nsfw"])
    fields: list[ArtistNegativeField] = Field(
        default_factory=lambda: ["negative_prompt", "after_negative_prompt"]
    )

    @field_validator("blocked_tokens", mode="before")
    @classmethod
    def normalize_blocked_tokens(cls, value: Any) -> list[str]:
        if value is None:
            return ["nsfw"]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []

    @field_validator("fields", mode="before")
    @classmethod
    def normalize_fields(cls, value: Any) -> list[str]:
        if value is None:
            return ["negative_prompt", "after_negative_prompt"]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []


class ArtistInputFilterConfig(BaseModel):
    negative_prompt: ArtistNegativePromptFilterConfig = Field(
        default_factory=ArtistNegativePromptFilterConfig
    )


class ArtistInputFilter:
    def __init__(self, config: ArtistInputFilterConfig | dict[str, Any] | None = None):
        self.config = ArtistInputFilterConfig.model_validate(config or {})

    def apply(self, artist: NovelAIArtist | NodeDocument):
        if isinstance(artist, NovelAIArtist):
            return self._apply_legacy_artist(artist)
        return self._apply_node(artist)

    def _apply_legacy_artist(self, artist: NovelAIArtist) -> NovelAIArtist:
        config = self.config.negative_prompt
        if not config.enabled:
            return artist
        working = artist.model_copy(deep=True)
        removed_by_field: dict[str, list[str]] = {}
        for field in config.fields:
            filtered, removed = _filter_prompt_text(
                getattr(working, field),
                blocked_tokens=config.blocked_tokens,
            )
            setattr(working, field, filtered)
            if removed:
                removed_by_field[field] = removed
        self._log_removed(working.artist_ref, removed_by_field)
        return working

    def _apply_node(self, artist: NodeDocument) -> NodeDocument:
        config = self.config.negative_prompt
        if not config.enabled:
            return artist
        working = artist.model_copy(deep=True)
        removed_by_field: dict[str, list[str]] = {}

        if "negative_prompt" in config.fields:
            working.negative_prompt, removed = _filter_prompt_values(
                working.negative_prompt,
                blocked_tokens=config.blocked_tokens,
            )
            if removed:
                removed_by_field["negative_prompt"] = removed

            filtered_fragments = []
            fragment_removed: list[str] = []
            for fragment in working.prompt.negative:
                filtered, removed = _filter_prompt_text(
                    fragment.text,
                    blocked_tokens=config.blocked_tokens,
                )
                fragment_removed.extend(removed)
                if filtered:
                    filtered_fragments.append(fragment.model_copy(update={"text": filtered}))
            working.prompt.negative = filtered_fragments
            if fragment_removed:
                removed_by_field["prompt.negative"] = fragment_removed

        renderers = dict(working.renderers)
        for backend, raw_payload in renderers.items():
            if not isinstance(raw_payload, dict):
                continue
            payload = dict(raw_payload)
            for field in config.fields:
                if field not in payload:
                    continue
                filtered, removed = _filter_prompt_value(
                    payload[field],
                    blocked_tokens=config.blocked_tokens,
                )
                payload[field] = filtered
                if removed:
                    removed_by_field[f"renderers.{backend}.{field}"] = removed
            renderers[backend] = payload
        working.renderers = renderers

        if removed_by_field:
            composition = dict(working.composition)
            composition["input_filter"] = {
                "negative_prompt": {
                    "blocked_tokens": list(config.blocked_tokens),
                    "removed_tokens": _dedupe(
                        token for values in removed_by_field.values() for token in values
                    ),
                    "affected_fields": list(removed_by_field),
                }
            }
            working.composition = composition
        self._log_removed(working.id, removed_by_field)
        return working

    def _log_removed(self, artist_id: str, removed_by_field: dict[str, list[str]]) -> None:
        if not removed_by_field:
            return
        logger.info(
            "ArtistInputFilter removed negative prompt tokens artist=%s fields=%s tokens=%s",
            artist_id,
            list(removed_by_field),
            _dedupe(token for values in removed_by_field.values() for token in values),
        )


def _filter_prompt_value(
    value: Any,
    *,
    blocked_tokens: list[str],
) -> tuple[Any, list[str]]:
    if isinstance(value, list):
        return _filter_prompt_values(value, blocked_tokens=blocked_tokens)
    return _filter_prompt_text(str(value or ""), blocked_tokens=blocked_tokens)


def _filter_prompt_values(
    values: list[Any],
    *,
    blocked_tokens: list[str],
) -> tuple[list[str], list[str]]:
    filtered_values: list[str] = []
    removed_tokens: list[str] = []
    for value in values:
        filtered, removed = _filter_prompt_text(
            str(value),
            blocked_tokens=blocked_tokens,
        )
        removed_tokens.extend(removed)
        if filtered:
            filtered_values.append(filtered)
    return filtered_values, removed_tokens


def _filter_prompt_text(
    text: str,
    *,
    blocked_tokens: list[str],
) -> tuple[str, list[str]]:
    blocked = {_canonical_token(value) for value in blocked_tokens if _canonical_token(value)}
    if not blocked:
        return str(text or ""), []
    raw_text = str(text or "")
    separator = ", " if ", " in raw_text else ","
    kept: list[str] = []
    removed: list[str] = []
    for raw_token in raw_text.strip(" ,").split(","):
        token = raw_token.strip()
        if not token:
            continue
        canonical = _canonical_token(token)
        if canonical in blocked:
            removed.append(canonical)
            continue
        kept.append(token)
    return separator.join(kept), removed


def _canonical_token(value: str) -> str:
    text = str(value or "").strip()
    numeric = _NUMERIC_WEIGHT_RE.match(text)
    if numeric:
        text = numeric.group(1).strip()
    while len(text) >= 2 and (text[0], text[-1]) in {("{", "}"), ("[", "]")}:
        text = text[1:-1].strip()
    text = _SPACE_RE.sub("_", text.lower()).replace("-", "_")
    return _UNDERSCORE_RE.sub("_", text).strip("_")


def _dedupe(values) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
