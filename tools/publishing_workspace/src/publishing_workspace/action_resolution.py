from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .logging import get_logger
from .models import AssetRecord, ImageNodeRef


logger = get_logger(__name__)
PHASE_PREFIXES = ("00_start", "01_pre", "02_core", "03_cum", "04_post")


@dataclass(frozen=True)
class ActionResolution:
    action_values: tuple[str, ...]
    group_values: tuple[str, ...]
    status: Literal["generated_new", "standalone_category", "unresolved", "missing"]
    warnings: tuple[str, ...] = ()


class ActionResolutionIndex:
    """索引原始 action 节点和最新的动态分类 manifest。"""

    def __init__(self, design_root: str | Path, *, action_root_name: str = "动作改2") -> None:
        self.design_root = Path(design_root).expanduser().resolve()
        self.action_root = (self.design_root / action_root_name).resolve()
        self.new_root = (self.action_root / "new").resolve()
        if not self.action_root.is_dir():
            raise FileNotFoundError(f"Action root not found: {self.action_root}")

        self.action_root_str = str(self.action_root).replace("\\", "/").casefold()
        self.action_marker = f"{self.action_root.name.casefold()}/"
        self._new_by_name: dict[str, set[str]] = defaultdict(set)
        self._source_groups: dict[str, list[str]] = defaultdict(list)
        self._dest_sources: dict[str, set[str]] = defaultdict(set)
        self._name_sources: dict[str, set[str]] = defaultdict(set)
        self._category_paths: dict[str, Path] = {}
        self._category_by_root: dict[str, list[Path]] = defaultdict(list)
        self._load_new_nodes()
        self._load_categories()
        self._load_manifest()

    def resolve(
        self,
        node: ImageNodeRef,
        *,
        explicit_groups: list[str],
    ) -> ActionResolution:
        raw_action = _node_value(node)
        if not raw_action:
            return ActionResolution((), tuple(explicit_groups), "missing")

        relative = self._relative_ref(node.ref)
        if relative:
            source_candidates = self._dest_sources.get(_key(relative), set())
            if len(source_candidates) == 1:
                return self._generated(next(iter(source_candidates)), explicit_groups)
            if len(source_candidates) > 1:
                return self._unresolved(
                    raw_action,
                    explicit_groups,
                    "category ref maps to multiple original action nodes",
                )

            if _is_new_relative(relative):
                source = _normalize_relative(relative)
                if _key(source) in self._all_sources():
                    return self._generated(source, explicit_groups)

            category = self._category_paths.get(_key(relative))
            if category is not None:
                group = _first_segment(relative)
                return ActionResolution(
                    (raw_action,),
                    _ordered_unique([*explicit_groups, group]),
                    "standalone_category",
                )

        source_candidates = self._name_candidates(raw_action)
        if len(source_candidates) == 1:
            return self._generated(next(iter(source_candidates)), explicit_groups)
        if len(source_candidates) > 1:
            return self._unresolved(
                raw_action,
                explicit_groups,
                "action name maps to multiple original action nodes",
            )

        topic = explicit_groups[0] if len(explicit_groups) == 1 else ""
        standalone = self._standalone_candidates(topic, raw_action)
        if len(standalone) == 1:
            return ActionResolution(
                (raw_action,),
                _ordered_unique([*explicit_groups, topic]),
                "standalone_category",
            )
        if len(standalone) > 1:
            return self._unresolved(
                raw_action,
                explicit_groups,
                "standalone action name is ambiguous",
            )

        return self._unresolved(
            raw_action,
            explicit_groups,
            "action cannot be mapped to new or a standalone category",
        )

    def _generated(self, source: str, explicit_groups: list[str]) -> ActionResolution:
        normalized_source = _normalize_relative(source)
        action = Path(normalized_source).name
        groups = self._source_groups.get(_key(normalized_source), [])
        if not groups:
            groups = explicit_groups
        warnings: tuple[str, ...] = ()
        if not groups:
            warnings = (f"action {action!r} is in new but has no current action_group",)
        return ActionResolution(
            (action,),
            tuple(_ordered_unique(groups)),
            "generated_new",
            warnings,
        )

    def _unresolved(
        self,
        action: str,
        groups: list[str],
        reason: str,
    ) -> ActionResolution:
        return ActionResolution(
            (action,),
            tuple(_ordered_unique(groups)),
            "unresolved",
            (f"action {action!r} unresolved: {reason}",),
        )

    def _name_candidates(self, value: str) -> set[str]:
        candidates: set[str] = set()
        for key in (value, strip_phase_prefix(value)):
            candidates.update(self._new_by_name.get(_key(key), set()))
            candidates.update(self._name_sources.get(_key(key), set()))
        return candidates

    def _standalone_candidates(self, topic: str, action: str) -> set[Path]:
        if not topic:
            return set()
        candidates: set[Path] = set()
        for path in self._category_by_root.get(_key(topic), []):
            name = path.name
            if name in {action, strip_phase_prefix(action)}:
                candidates.add(path)
                continue
            for target in {action, strip_phase_prefix(action)}:
                if target and re.fullmatch(rf"\d+_{re.escape(target)}", name):
                    candidates.add(path)
        return candidates

    def _relative_ref(self, ref: str | None) -> str:
        if not ref:
            return ""
        value = str(ref).strip()
        norm = value.replace("\\", "/")
        norm_cf = norm.casefold()

        if norm_cf.startswith(self.action_root_str):
            rel = norm[len(self.action_root_str) :].lstrip("/")
            return rel.replace("\\", "/")

        normalized = _normalize_relative(value)
        if normalized.casefold().startswith(self.action_marker):
            return normalized[len(self.action_marker) :]
        return normalized if "/" in normalized else ""

    def _all_sources(self) -> set[str]:
        return {
            *self._source_groups.keys(),
            *(_key(source) for sources in self._new_by_name.values() for source in sources),
        }

    def _load_new_nodes(self) -> None:
        if not self.new_root.is_dir():
            return
        try:
            entries = sorted(os.scandir(self.new_root), key=lambda item: item.name.casefold())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir():
                source = f"new/{entry.name}"
                self._new_by_name[_key(entry.name)].add(source)

    def _load_categories(self) -> None:
        try:
            entries = sorted(os.scandir(self.action_root), key=lambda item: item.name.casefold())
        except OSError:
            return
        for root_entry in entries:
            if not root_entry.is_dir() or root_entry.name.casefold() == "new":
                continue
            root_path = Path(root_entry.path)
            root_key = _key(root_entry.name)
            by_root = self._category_by_root[root_key]
            try:
                child_entries = sorted(
                    os.scandir(root_entry.path), key=lambda item: item.name.casefold()
                )
            except OSError:
                continue
            for child_entry in child_entries:
                if not child_entry.is_dir():
                    continue
                child_path = Path(child_entry.path)
                rel_posix = f"{root_entry.name}/{child_entry.name}"
                self._category_paths[_key(rel_posix)] = child_path
                by_root.append(child_path)

    def _load_manifest(self) -> None:
        manifest = self.action_root / "category_view_manifest.json"
        if not manifest.is_file():
            return
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError(f"Invalid action category manifest: {manifest}")
        for item in data["items"]:
            if not isinstance(item, dict):
                continue
            source = _normalize_relative(item.get("source"))
            if not source or not _is_new_relative(source):
                continue
            root = str(item.get("root") or "").strip()
            dest = _normalize_relative(item.get("dest"))
            if root and root.casefold() not in {
                value.casefold() for value in self._source_groups[_key(source)]
            }:
                self._source_groups[_key(source)].append(root)
            if dest:
                self._dest_sources[_key(dest)].add(source)
            for name in (item.get("name"), item.get("view_name")):
                text = str(name or "").strip()
                if text:
                    self._name_sources[_key(text)].add(source)


class ActionNodeValueResolver:
    """为分类投影提供稳定 action 和最新 action_group 值。"""

    def __init__(
        self,
        *,
        design_root: str | Path | None = None,
        action_root_name: str = "动作改2",
        enabled: bool = True,
    ) -> None:
        self.design_root = Path(design_root).expanduser().resolve() if design_root else None
        self.action_root_name = action_root_name
        self.enabled = enabled
        self._indexes: dict[Path, ActionResolutionIndex] = {}
        self._unavailable_roots: set[Path] = set()
        self._asset_cache: dict[str, ActionResolution] = {}
        self._warnings: list[str] = []
        self._warning_keys: set[str] = set()

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def values_for(self, asset: AssetRecord, role: str) -> list[str]:
        if not self.enabled or role not in {"action", "action_group"}:
            return asset.node_info.values_for(role)
        resolution = self._resolve_asset(asset)
        return list(resolution.action_values if role == "action" else resolution.group_values)

    def _resolve_asset(self, asset: AssetRecord) -> ActionResolution:
        cached = self._asset_cache.get(asset.asset_id)
        if cached is not None:
            return cached

        action_nodes = [node for node in asset.node_info.nodes if node.role == "action"]
        explicit_groups = asset.node_info.values_for("action_group")
        if not action_nodes:
            raw_actions = asset.node_info.values_for("action")
            result = ActionResolution(
                tuple(raw_actions),
                tuple(explicit_groups),
                "unresolved" if raw_actions else "missing",
                (),
            )
            self._asset_cache[asset.asset_id] = result
            return result

        action_values: list[str] = []
        group_values: list[str] = []
        statuses: list[str] = []
        warnings: list[str] = []
        for node in action_nodes:
            index = self._index_for(node.ref)
            if index is None:
                raw = _node_value(node)
                current = ActionResolution(
                    (raw,) if raw else (),
                    tuple(explicit_groups),
                    "unresolved" if raw else "missing",
                    (f"action {raw!r} has no resolvable design index",) if raw else (),
                )
            else:
                current = index.resolve(node, explicit_groups=explicit_groups)
            action_values.extend(current.action_values)
            group_values.extend(current.group_values)
            statuses.append(current.status)
            warnings.extend(current.warnings)

        status = "generated_new" if "generated_new" in statuses else (
            "standalone_category" if "standalone_category" in statuses else statuses[0]
        )
        result = ActionResolution(
            tuple(_ordered_unique(action_values)),
            tuple(_ordered_unique(group_values)),
            status, 
            tuple(_ordered_unique(warnings)),
        )
        self._asset_cache[asset.asset_id] = result
        for warning in result.warnings:
            if warning not in self._warning_keys:
                self._warning_keys.add(warning)
                self._warnings.append(warning)
                logger.warning("Publishing action resolution: %s", warning)
        return result

    def _index_for(self, ref: str | None) -> ActionResolutionIndex | None:
        roots: list[tuple[Path, str]] = []
        if self.design_root is not None:
            roots.append((self.design_root, self.action_root_name))
        if ref:
            path = Path(ref).expanduser()
            if path.is_absolute():
                manifest = _find_manifest(path)
                if manifest is not None:
                    roots.append((manifest.parent.parent, manifest.parent.name))
        for root, action_root_name in roots:
            key = root.resolve()
            if key in self._indexes:
                return self._indexes[key]
            if key in self._unavailable_roots:
                continue
            try:
                index = ActionResolutionIndex(key, action_root_name=action_root_name)
            except (FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
                self._unavailable_roots.add(key)
                logger.warning("Unable to build action resolution index: %s", exc)
                continue
            self._indexes[key] = index
            return index
        return None


_MANIFEST_PATH_CACHE: dict[str, Path | None] = {}


def _find_manifest(path: Path) -> Path | None:
    start = path if path.is_dir() else path.parent
    key = str(start.resolve())
    if key in _MANIFEST_PATH_CACHE:
        return _MANIFEST_PATH_CACHE[key]
    found: Path | None = None
    for candidate in (start, *start.parents):
        manifest = candidate / "category_view_manifest.json"
        if manifest.is_file():
            found = manifest.resolve()
            break
    _MANIFEST_PATH_CACHE[key] = found
    return found


def _node_value(node: ImageNodeRef) -> str:
    if node.id:
        return node.id.strip()
    if node.ref:
        return Path(node.ref.replace("\\", "/").rstrip("/")).name.strip()
    return ""


def _normalize_relative(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _is_new_relative(value: str) -> bool:
    return _normalize_relative(value).casefold().startswith("new/")


def _first_segment(value: str) -> str:
    return _normalize_relative(value).split("/", 1)[0]


def _key(value: object) -> str:
    return _normalize_relative(value).casefold()


def strip_phase_prefix(value: str) -> str:
    cleaned = str(value or "").strip()
    for prefix in PHASE_PREFIXES:
        marker = f"{prefix}_"
        if cleaned.startswith(marker):
            return cleaned[len(marker) :]
    return cleaned


def _ordered_unique(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
