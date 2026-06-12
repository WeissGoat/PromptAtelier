from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .models import BatchSpec


def load_batch_spec(path: str | Path) -> BatchSpec:
    spec_path = Path(path)
    data = _read_mapping(spec_path)
    return BatchSpec.model_validate(data)


def _read_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
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
