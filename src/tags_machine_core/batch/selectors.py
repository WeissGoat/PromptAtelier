from __future__ import annotations

import csv
import glob
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import PromptItem, SelectorSpec
from .spec_reader import resolve_path


@dataclass(frozen=True)
class SelectorContext:
    base_dir: Path
    collections: dict[str, dict[str, list[str]]]


def expand_selector(
    *,
    role: str,
    spec: SelectorSpec,
    context: SelectorContext,
) -> list[Any]:
    selector = spec.selector.strip()
    if selector == "explicit":
        if role == "artist":
            return [str(ref) for ref in spec.refs]
        return [str(resolve_ref(ref, context.base_dir)) for ref in spec.refs]
    if selector == "folder":
        if not spec.root:
            raise ValueError("folder selector requires root")
        return _discover_nodes(resolve_ref(spec.root, context.base_dir), spec)
    if selector == "collection":
        return _expand_collection(role=role, spec=spec, context=context)
    if selector == "glob":
        if not spec.pattern:
            raise ValueError("glob selector requires pattern")
        return _glob_nodes(spec.pattern, context.base_dir, spec)
    if selector == "prompt_list":
        return [PromptItem.model_validate(item) for item in spec.items]
    if selector == "prompt_file":
        if not spec.path:
            raise ValueError("prompt_file selector requires path")
        return _read_prompt_file(resolve_path(spec.path, base_dir=context.base_dir), spec.format)
    raise ValueError(f"Unsupported selector: {selector}")


def resolve_ref(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def _expand_collection(
    *,
    role: str,
    spec: SelectorSpec,
    context: SelectorContext,
) -> list[str]:
    if not spec.name:
        raise ValueError("collection selector requires name")
    collection_name = f"{role}s"
    roots = context.collections.get(collection_name, {}).get(spec.name, [])
    if not roots:
        raise ValueError(f"Unknown {role} collection: {spec.name}")
    result: list[str] = []
    for root in roots:
        result.extend(_discover_nodes(resolve_ref(root, context.base_dir), spec))
    return _dedupe(result)


def _discover_nodes(root: Path, spec: SelectorSpec) -> list[str]:
    if not root.exists():
        raise FileNotFoundError(f"Selector root not found: {root}")
    if root.is_file():
        return [str(root)]

    candidates = [root]
    if spec.recursive:
        candidates.extend(path for path in root.rglob("*") if path.is_dir())
    else:
        candidates.extend(path for path in root.iterdir() if path.is_dir())

    result: list[str] = []
    for candidate in sorted(candidates, key=_natural_sort_key):
        if _excluded(candidate, spec):
            continue
        if not _included(candidate, spec):
            continue
        if _has_node_file(candidate, spec.node_files):
            result.append(str(candidate))

    if spec.shuffle:
        random.shuffle(result)
    if spec.limit is not None:
        result = result[: spec.limit]
    return _dedupe(result)


def _glob_nodes(pattern: str, base_dir: Path, spec: SelectorSpec) -> list[str]:
    resolved_pattern = pattern if Path(pattern).is_absolute() else str(base_dir / pattern)
    matches = sorted(glob.glob(resolved_pattern, recursive=True), key=_natural_sort_key)
    result: list[str] = []
    for value in matches:
        path = Path(value)
        result.append(str(path.parent if path.is_file() else path))
    result = _dedupe(result)
    if spec.limit is not None:
        result = result[: spec.limit]
    return result


def _read_prompt_file(path: Path, format_name: str) -> list[PromptItem]:
    format_name = format_name.strip().lower()
    if format_name == "lines":
        items = []
        for line in path.read_text(encoding="utf-8").splitlines():
            prompt = line.strip()
            if not prompt or prompt.startswith("#"):
                continue
            items.append(PromptItem(id=f"{path.stem}_{len(items) + 1:04d}", prompt=prompt))
        return items
    if format_name == "jsonl":
        return [
            PromptItem.model_validate(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if format_name == "json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"prompt_file json must be a list: {path}")
        return [PromptItem.model_validate(item) for item in data]
    if format_name == "yaml":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(data, list):
            raise ValueError(f"prompt_file yaml must be a list: {path}")
        return [PromptItem.model_validate(item) for item in data]
    if format_name == "csv":
        with path.open("r", encoding="utf-8", newline="") as f:
            return [PromptItem.model_validate(row) for row in csv.DictReader(f)]
    raise ValueError(f"Unsupported prompt_file format: {format_name}")


def _has_node_file(path: Path, node_files: list[str]) -> bool:
    return any((path / name).exists() for name in node_files)


def _excluded(path: Path, spec: SelectorSpec) -> bool:
    names = set(spec.exclude.get("names") or [])
    if path.name in names:
        return True
    patterns = [str(item) for item in spec.exclude.get("paths") or []]
    return any(path.match(pattern) for pattern in patterns)


def _included(path: Path, spec: SelectorSpec) -> bool:
    if not spec.include:
        return True
    names = set(spec.include.get("names") or [])
    if names and path.name not in names:
        return False
    patterns = [str(item) for item in spec.include.get("paths") or []]
    if patterns and not any(path.match(pattern) for pattern in patterns):
        return False
    return True


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _natural_sort_key(value: str | Path) -> list[int | str]:
    text = str(value)
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]
