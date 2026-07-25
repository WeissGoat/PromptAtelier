from __future__ import annotations

import glob
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import NodePoolSource


@dataclass(frozen=True)
class NodePoolSelectorContext:
    base_dir: Path
    collections: dict[str, dict[str, list[Any]]]


def expand_node_pool_source(
    *,
    role: str,
    source: NodePoolSource,
    context: NodePoolSelectorContext,
    collection_stack: tuple[str, ...] = (),
) -> list[str]:
    if source.type == "folder":
        return _discover_nodes(_resolve(source.value, context.base_dir), source)
    if source.type == "glob":
        return _glob_nodes(source.value, context.base_dir, source)
    if source.type == "collection":
        return _expand_collection(
            role=role,
            name=source.value,
            context=context,
            collection_stack=collection_stack,
        )
    raise ValueError(f"Unsupported node pool source: {source.type}")


def _expand_collection(
    *,
    role: str,
    name: str,
    context: NodePoolSelectorContext,
    collection_stack: tuple[str, ...],
) -> list[str]:
    collection_group = f"{role}s"
    key = f"{collection_group}.{name}"
    if key in collection_stack:
        raise ValueError(f"Circular collection reference detected: {' -> '.join([*collection_stack, key])}")
    items = context.collections.get(collection_group, {}).get(name)
    if items is None:
        raise ValueError(f"Unknown {role} collection: {name}")
    result: list[str] = []
    stack = (*collection_stack, key)
    for item in items:
        if isinstance(item, dict):
            if "collection" in item:
                result.extend(_expand_collection(
                    role=role,
                    name=str(item["collection"]),
                    context=context,
                    collection_stack=stack,
                ))
                continue
            selector = _source_from_collection_item(item)
            result.extend(expand_node_pool_source(
                role=role,
                source=selector,
                context=context,
                collection_stack=stack,
            ))
            continue
        raw = str(item).strip()
        if not raw:
            continue
        if role == "artist" and not Path(raw).is_absolute():
            result.append(raw)
        else:
            path = _resolve(raw, context.base_dir)
            if path.is_dir() and _has_node_file(path):
                result.append(str(path))
            else:
                result.extend(_discover_nodes(path, NodePoolSource(type="folder", value=str(path))))
    return _dedupe(result)


def _source_from_collection_item(item: dict[str, Any]) -> NodePoolSource:
    selector = str(item.get("selector") or "").strip()
    if selector == "folder":
        include = item.get("include") if isinstance(item.get("include"), dict) else {}
        exclude = item.get("exclude") if isinstance(item.get("exclude"), dict) else {}
        return NodePoolSource(
            type="folder",
            value=str(item.get("root") or ""),
            recursive=bool(item.get("recursive", False)),
            include_names=list(include.get("names") or []),
            exclude_names=list(exclude.get("names") or []),
        )
    if selector == "glob":
        return NodePoolSource(type="glob", value=str(item.get("pattern") or ""))
    if selector == "collection":
        return NodePoolSource(type="collection", value=str(item.get("name") or ""))
    raise ValueError(f"Collection item uses unsupported node selector: {selector or '<empty>'}")


def _discover_nodes(root: Path, source: NodePoolSource) -> list[str]:
    if not root.exists():
        raise FileNotFoundError(f"Selector root not found: {root}")
    if root.is_file():
        return [str(root.parent)]
    candidates = [root]
    candidates.extend(
        path for path in (root.rglob("*") if source.recursive else root.iterdir()) if path.is_dir()
    )
    result: list[str] = []
    for candidate in sorted(candidates, key=_natural_sort_key):
        if _matches_any(candidate.name, source.exclude_names):
            continue
        if source.include_names and not _matches_any(candidate.name, source.include_names):
            continue
        if candidate != root and source.include_names:
            result.extend(_discover_nodes(
                candidate,
                source.model_copy(update={"include_names": [], "exclude_names": []}),
            ))
            continue
        if _has_node_file(candidate):
            result.append(str(candidate))
    return _dedupe(result)


def _glob_nodes(pattern: str, base_dir: Path, source: NodePoolSource) -> list[str]:
    resolved = pattern if Path(pattern).is_absolute() else str(base_dir / pattern)
    result: list[str] = []
    for value in sorted(glob.glob(resolved, recursive=True), key=_natural_sort_key):
        path = Path(value)
        candidate = path.parent if path.is_file() else path
        if _has_node_file(candidate):
            result.append(str(candidate))
    return _dedupe(result)


def _resolve(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def _has_node_file(path: Path) -> bool:
    return any((path / name).exists() for name in ("meta.yaml", "node.yaml", "tags.txt"))


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(name == pattern or Path(name).match(pattern) for pattern in patterns)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _natural_sort_key(value: str | Path) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value))]
