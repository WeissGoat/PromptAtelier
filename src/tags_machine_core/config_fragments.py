from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def load_required_file(path: str | Path, *, stack: list[Path] | None = None) -> dict[str, Any]:
    source = Path(path)
    resolved = source.resolve()
    active = stack or []
    if resolved in active:
        chain = " -> ".join(str(item) for item in [*active, resolved])
        raise ValueError(f"Circular require detected: {chain}")
    return load_required_mapping(
        read_mapping(source),
        base_path=source,
        stack=[*active, resolved],
    )


def load_required_mapping(
    data: dict[str, Any],
    *,
    base_path: str | Path | None = None,
    stack: list[Path] | None = None,
) -> dict[str, Any]:
    requirements = normalize_require(data.get("require"))
    merged: dict[str, Any] = {}
    source = Path(base_path) if base_path else None
    base_dir = source.parent if source else Path(".")
    for item in requirements:
        required = resolve_path(item, base_dir=base_dir)
        merged = merge_mappings(merged, load_required_file(required, stack=stack))
    current = dict(data)
    current.pop("require", None)
    merged = merge_mappings(merged, current)
    merged["require"] = requirements
    return merged


def read_mapping(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    text = source.read_text(encoding="utf-8-sig")
    data = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuration fragment must be a mapping: {source}")
    return data


def normalize_require(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError("require must be a string or list of strings")


def merge_mappings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_mappings(result[key], value)
        else:
            result[key] = value
    return result


def resolve_path(value: str | Path, *, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path
