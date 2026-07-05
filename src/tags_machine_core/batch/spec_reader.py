from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .models import BatchSpec


def load_batch_spec(path: str | Path) -> BatchSpec:
    spec_path = Path(path)
    data = load_batch_spec_data(spec_path)
    return BatchSpec.model_validate(data)


def load_batch_spec_mapping(data: dict[str, Any], *, base_path: str | Path | None = None) -> BatchSpec:
    merged = _load_mapping_with_require_data(data, base_path=Path(base_path) if base_path else None)
    merged = _expand_batch_shorthand(merged)
    return BatchSpec.model_validate(merged)


def load_batch_spec_data(path: str | Path) -> dict[str, Any]:
    spec_path = Path(path)
    data = _load_mapping_with_require(spec_path, stack=[])
    return _expand_batch_shorthand(data)


def _load_mapping_with_require(path: Path, *, stack: list[Path]) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved in stack:
        chain = " -> ".join(str(item) for item in [*stack, resolved])
        raise ValueError(f"Circular batch require detected: {chain}")

    data = _read_mapping(path)
    return _load_mapping_with_require_data(data, base_path=path, stack=[*stack, resolved])


def _load_mapping_with_require_data(
    data: dict[str, Any],
    *,
    base_path: Path | None,
    stack: list[Path] | None = None,
) -> dict[str, Any]:
    stack = stack or []
    requirements = _normalize_require(data.get("require"))
    merged: dict[str, Any] = {}
    base_dir = base_path.parent if base_path else Path(".")
    for item in requirements:
        required_path = resolve_path(item, base_dir=base_dir)
        required_data = _load_mapping_with_require(required_path, stack=stack)
        merged = _merge_mappings(merged, required_data)
    current = dict(data)
    current.pop("require", None)
    merged = _merge_mappings(merged, current)
    merged["require"] = requirements
    return merged


def _read_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Batch spec must be a mapping: {path}")
    return data


def resolve_path(value: str | Path, *, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def _normalize_require(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    raise ValueError("batch require must be a string or list of strings")


def _merge_mappings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _merge_mappings(result[key], value)
        else:
            result[key] = value
    return result


def _expand_batch_shorthand(data: dict[str, Any]) -> dict[str, Any]:
    shorthand = data.get("batch")
    if shorthand is None:
        return data
    if not isinstance(shorthand, dict):
        raise ValueError("batch shorthand must be a mapping")

    result = dict(data)
    result.pop("batch", None)

    defaults_patch = _batch_defaults_patch(shorthand)
    if defaults_patch:
        result["defaults"] = _merge_mappings(result.get("defaults") or {}, defaults_patch)

    select_patch = _batch_select_patch(shorthand)
    if select_patch:
        result["select"] = _merge_mappings(result.get("select") or {}, select_patch)

    expand_patch = _batch_expand_patch(shorthand)
    if expand_patch:
        result["expand"] = _merge_mappings(result.get("expand") or {}, expand_patch)

    return result


def _batch_defaults_patch(shorthand: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "artist": "artist",
        "composer": "composer",
        "nt": "nt",
        "resolution": "resolution",
        "model": "model",
    }
    return {target: shorthand[source] for source, target in mapping.items() if source in shorthand}


def _batch_expand_patch(shorthand: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "mode": "mode",
        "strategy": "action_group_strategy",
        "max_tasks": "max_tasks",
        "auto_num": "auto_num",
        "action_group_record": "action_group_record",
        "allow_fill_missing_cp_from_candidates": "allow_fill_missing_cp_from_candidates",
    }
    patch = {target: shorthand[source] for source, target in mapping.items() if source in shorthand}
    if "mode" not in patch and "action_groups" in shorthand:
        patch["mode"] = "blackboard_rounds"
    return patch


def _batch_select_patch(shorthand: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if "characters" in shorthand:
        patch["characters"] = [
            _collection_selector(value) for value in _as_list(shorthand["characters"])
        ]
    if "action_groups" in shorthand:
        patch["action_groups"] = [
            _action_group_selector(value) for value in _as_list(shorthand["action_groups"])
        ]
    if "artists" in shorthand:
        patch["artists"] = [
            _collection_selector(value) for value in _as_list(shorthand["artists"])
        ]
    return patch


def _collection_selector(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"selector": "collection", "name": str(value)}


def _action_group_selector(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    name = str(value)
    return {"name": name, "selector": "collection"}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
