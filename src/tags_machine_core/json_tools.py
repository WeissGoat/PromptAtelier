from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel


IMAGE_LIKE_KEYS = {
    "image",
    "mask",
    "reference_image_multiple",
    "director_reference_images",
}


def to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Path):
        return str(value)
    return value


def sanitize_json_for_display(
    value: Any,
    *,
    full: bool = False,
    max_string_length: int = 2000,
    max_image_string_length: int = 60,
) -> Any:
    data = to_jsonable(value)
    if full:
        return data
    return _sanitize_value(
        data,
        parent_key=None,
        max_string_length=max_string_length,
        max_image_string_length=max_image_string_length,
    )


def _sanitize_value(
    value: Any,
    *,
    parent_key: str | None,
    max_string_length: int,
    max_image_string_length: int,
) -> Any:
    value = to_jsonable(value)
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(
                item,
                parent_key=str(key),
                max_string_length=max_string_length,
                max_image_string_length=max_image_string_length,
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_value(
                item,
                parent_key=parent_key,
                max_string_length=max_string_length,
                max_image_string_length=max_image_string_length,
            )
            for item in value
        ]
    if isinstance(value, bytes):
        return f"<bytes length={len(value)}>"
    if isinstance(value, str):
        limit = max_image_string_length if parent_key in IMAGE_LIKE_KEYS else max_string_length
        if len(value) > limit:
            return f"{value[:limit]}...(truncated, chars={len(value)})"
    return value
