from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import CLASSIFY_FIELDS


class MissingClassifyError(FileNotFoundError):
    pass


def load_classify_tags(node_dir: str | Path) -> dict[str, set[str]]:
    path = Path(node_dir) / "classify.yaml"
    if not path.exists():
        raise MissingClassifyError(str(path))
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"classify.yaml must be a mapping: {path}")
    result: dict[str, set[str]] = {field: set() for field in CLASSIFY_FIELDS}
    for field in CLASSIFY_FIELDS:
        value = data.get(field)
        if field == "subtype":
            result[field] = _flatten_subtype(value, path)
        else:
            result[field] = _as_tokens(value, path=path, field=field)
    return result


def _flatten_subtype(value: Any, path: Path) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, dict):
        raise ValueError(f"classify.yaml subtype must be a mapping: {path}")
    result: set[str] = set()
    for items in value.values():
        result.update(_as_tokens(items, path=path, field="subtype"))
    return result


def _as_tokens(value: Any, *, path: Path, field: str) -> set[str]:
    if value is None or value == "":
        return set()
    items = value if isinstance(value, list) else [value]
    result: set[str] = set()
    for item in items:
        if isinstance(item, (dict, list)):
            raise ValueError(f"classify.yaml {field} contains an invalid value: {path}")
        text = str(item).strip().lower()
        if text:
            result.add(text)
    return result
