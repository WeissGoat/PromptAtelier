from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


PHASE_PREFIXES = ("00_start", "01_pre", "02_core", "03_cum", "04_post")


class ActionIndexError(RuntimeError):
    """Action 节点索引无法建立。"""


class ActionNodeIndex:
    def __init__(self, design_root: str | Path, action_dir_name: str = "动作改2") -> None:
        self.design_root = Path(design_root).resolve()
        self.action_root = (self.design_root / action_dir_name).resolve()
        self.new_root = (self.action_root / "new").resolve()
        if not self.design_root.is_dir():
            raise ActionIndexError(f"design_root 不存在：{self.design_root}")
        if not self.action_root.is_dir():
            raise ActionIndexError(f"Action 根目录不存在：{self.action_root}")

        self.by_dest: dict[str, set[Path]] = defaultdict(set)
        self.by_root_view: dict[tuple[str, str], set[Path]] = defaultdict(set)
        self.by_view: dict[str, set[Path]] = defaultdict(set)
        self.by_name: dict[str, set[Path]] = defaultdict(set)
        self.new_by_name: dict[str, set[Path]] = defaultdict(set)
        self.category_by_relative: dict[str, Path] = {}
        self.category_by_root: dict[str, list[Path]] = defaultdict(list)

        self._load_new_nodes()
        self._load_categories()
        self._load_manifest()

    def manifest_by_dest(self, value: str) -> set[Path]:
        return set(self.by_dest.get(normalize_relative_path(value), set()))

    def manifest_by_root_view(self, root: str, view_name: str) -> set[Path]:
        return set(self.by_root_view.get((clean_text(root), clean_text(view_name)), set()))

    def manifest_by_view_or_name(self, value: str) -> set[Path]:
        cleaned = clean_text(value)
        return set(self.by_view.get(cleaned, set())) | set(self.by_name.get(cleaned, set()))

    def new_name_candidates(self, value: str) -> set[Path]:
        return set(self.new_by_name.get(clean_text(value), set()))

    def category_path(self, value: str) -> Path | None:
        return self.category_by_relative.get(normalize_relative_path(value))

    def category_candidates(self, topic: str, action: str) -> set[Path]:
        root = clean_text(topic)
        action_name = clean_text(action)
        if not root or not action_name:
            return set()
        stripped = strip_phase_prefix(action_name)
        candidates: set[Path] = set()
        for path in self.category_by_root.get(root, []):
            name = path.name
            if name in {action_name, stripped}:
                candidates.add(path)
                continue
            for target in {action_name, stripped}:
                if target and re.fullmatch(rf"\d+_{re.escape(target)}", name):
                    candidates.add(path)
                    break
        return candidates

    def relative_to_action_root(self, path: str | Path) -> str | None:
        try:
            return Path(path).resolve().relative_to(self.action_root).as_posix()
        except (OSError, ValueError):
            return None

    def relative_to_design_root(self, path: str | Path) -> str:
        try:
            return Path(path).resolve().relative_to(self.design_root).as_posix()
        except (OSError, ValueError) as exc:
            raise ActionIndexError(f"Action 路径不在 design_root 下：{path}") from exc

    def _load_new_nodes(self) -> None:
        if not self.new_root.is_dir():
            return
        for path in sorted(self.new_root.iterdir(), key=lambda item: item.name):
            if path.is_dir():
                self.new_by_name[path.name].add(path.resolve())

    def _load_categories(self) -> None:
        for root in sorted(self.action_root.iterdir(), key=lambda item: item.name):
            if not root.is_dir() or root.resolve() == self.new_root:
                continue
            for child in sorted(root.iterdir(), key=lambda item: item.name):
                if not child.is_dir():
                    continue
                resolved = child.resolve()
                relative = resolved.relative_to(self.action_root).as_posix()
                self.category_by_relative[relative] = resolved
                self.category_by_root[root.name].append(resolved)

    def _load_manifest(self) -> None:
        manifest_path = self.action_root / "category_view_manifest.json"
        if not manifest_path.is_file():
            return
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ActionIndexError(f"无法读取 Action manifest：{manifest_path}：{exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ActionIndexError(f"Action manifest 格式无效：{manifest_path}")
        for item in data["items"]:
            self._index_manifest_item(item)

    def _index_manifest_item(self, item: Any) -> None:
        if not isinstance(item, dict):
            return
        source = normalize_relative_path(str(item.get("source") or ""))
        if not source:
            return
        source_path = (self.action_root / Path(source)).resolve()
        if not source_path.is_dir() or not _is_relative_to(source_path, self.new_root):
            return

        dest = normalize_relative_path(str(item.get("dest") or ""))
        root = clean_text(item.get("root"))
        view_name = clean_text(item.get("view_name"))
        name = clean_text(item.get("name"))
        if dest:
            self.by_dest[dest].add(source_path)
        if root and view_name:
            self.by_root_view[(root, view_name)].add(source_path)
        if view_name:
            self.by_view[view_name].add(source_path)
        if name:
            self.by_name[name].add(source_path)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip()


def normalize_relative_path(value: str) -> str:
    return value.replace("\\", "/").strip().strip("/")


def strip_phase_prefix(value: str) -> str:
    cleaned = clean_text(value)
    for prefix in PHASE_PREFIXES:
        marker = f"{prefix}_"
        if cleaned.startswith(marker):
            return cleaned[len(marker) :]
    return cleaned


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
