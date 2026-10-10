"""素材库索引：角色、动作节点的去重搜索，动作按 classify.yaml 分面筛选。

- 角色库里有整目录复制出来的副本（"xxx - 快捷方式"），内容和原目录一样：按内容合并成一条，
  名字去掉副本后缀，代表目录优先取不带后缀的原目录；
- 内容比对忽略 meta.yaml 里随目录名变的 id、name、description 和 legacy 来源记录；
- 动作库有七千多个目录：一次 scandir 拿到文件列表和修改时间，只重新读改过的目录；
  读出的指纹和分面存到磁盘，服务重启后不必全部重读。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


FACET_FIELDS = ("cast", "domain", "subtype", "pose", "environment", "clothing", "tone", "flags", "phase")
NODE_FILES = ("meta.yaml", "node.yaml", "tags.txt")
_WATCHED_FILES = {*NODE_FILES, "classify.yaml"}
_IDENTITY_KEYS = {"id", "name", "description", "legacy"}
_COPY_SUFFIX = re.compile(r"\s*-\s*(?:快捷方式|副本|copy)\s*(?:\(\d+\)|\d+)?\s*$", re.IGNORECASE)
_REFRESH_SECONDS = 60.0
_CACHE_SCHEMA = "tags-machine-core.style-lab.library-cache/v1"
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def display_name(dirname: str) -> str:
    return _COPY_SUFFIX.sub("", dirname).strip() or dirname


def is_copy_name(dirname: str) -> bool:
    return bool(_COPY_SUFFIX.search(dirname))


@dataclass
class _DirInfo:
    signature: tuple
    fingerprint: str
    facets: dict[str, list[str]]


@dataclass
class LibraryEntry:
    role: str
    name: str
    path: Path
    relative: str
    copies: list[str] = field(default_factory=list)
    facets: dict[str, list[str]] = field(default_factory=dict)
    search_text: str = ""

    def as_dict(self, *, has_preview: bool) -> dict[str, Any]:
        return {
            "role": self.role,
            "name": self.name,
            "ref": str(self.path),
            "relative": self.relative,
            "has_preview": has_preview,
            "copies": len(self.copies),
            "copy_paths": self.copies[:8],
            "facets": self.facets,
        }


class LibraryIndex:
    def __init__(
        self,
        roots_for: Callable[[str], list[Path]],
        has_preview: Callable[[Path], bool],
        *,
        cache_path: Path | None = None,
        refresh_seconds: float = _REFRESH_SECONDS,
    ):
        self._roots_for = roots_for
        self._has_preview = has_preview
        self._cache_path = cache_path
        self._refresh_seconds = refresh_seconds
        self._lock = threading.Lock()
        self._dirs: dict[str, _DirInfo] | None = None
        self._entries: dict[str, tuple[float, list[LibraryEntry]]] = {}

    def entries(self, role: str, *, refresh: bool = False) -> list[LibraryEntry]:
        with self._lock:
            cached = self._entries.get(role)
            if cached and not refresh and time.monotonic() - cached[0] < self._refresh_seconds:
                return cached[1]
            entries = self._build(role)
            self._entries[role] = (time.monotonic(), entries)
            return entries

    def search(
        self,
        role: str,
        query: str = "",
        facets: dict[str, list[str]] | None = None,
        *,
        offset: int = 0,
        limit: int = 30,
        refresh: bool = False,
    ) -> dict[str, Any]:
        entries = self.entries(role, refresh=refresh)
        needles = [part for part in query.lower().split() if part]
        chosen = {key: set(values) for key, values in (facets or {}).items() if values}
        texted = [entry for entry in entries if all(needle in entry.search_text for needle in needles)]
        matched = [entry for entry in texted if _facets_match(entry, chosen)]
        if needles:
            # 名字里就能找到的排前面，只在路径里命中的放后面。
            matched.sort(key=lambda entry: 0 if all(needle in entry.name.lower() for needle in needles) else 1)
        page = matched[offset : offset + limit]
        options: dict[str, list[dict[str, Any]]] = {}
        if any(entry.facets for entry in entries):
            for name in FACET_FIELDS:
                # 某个分面的计数不受它自己的选择影响，选了一个值还能看到别的值有多少。
                counts = Counter(
                    value
                    for entry in texted
                    if _facets_match(entry, chosen, skip=name)
                    for value in entry.facets.get(name, [])
                )
                if counts:
                    options[name] = [{"value": value, "count": count} for value, count in counts.most_common()]
        return {
            "nodes": [entry.as_dict(has_preview=self._has_preview(entry.path)) for entry in page],
            "total": len(matched),
            "has_more": offset + limit < len(matched),
            "facet_options": options,
        }

    def _build(self, role: str) -> list[LibraryEntry]:
        if self._dirs is None:
            self._dirs = self._load_cache()
        groups: dict[str, list[tuple[Path, str, _DirInfo]]] = {}
        order: list[str] = []
        changed = False
        for root in self._roots_for(role):
            if not root.is_dir():
                continue
            for node_dir, signature in iter_node_dirs(root):
                key = str(node_dir)
                info = self._dirs.get(key)
                if info is None or info.signature != signature:
                    info = _DirInfo(signature, content_fingerprint(node_dir), read_facets(node_dir))
                    self._dirs[key] = info
                    changed = True
                relative = node_dir.relative_to(root).as_posix()
                if info.fingerprint not in groups:
                    groups[info.fingerprint] = []
                    order.append(info.fingerprint)
                groups[info.fingerprint].append((node_dir, relative, info))
        entries = []
        for fingerprint in order:
            members = sorted(groups[fingerprint], key=lambda item: (is_copy_name(item[0].name), len(item[1]), item[1]))
            path, relative, info = members[0]
            names = {display_name(member[0].name) for member in members}
            entries.append(
                LibraryEntry(
                    role=role,
                    name=display_name(path.name),
                    path=path,
                    relative=relative,
                    copies=[member[1] for member in members[1:]],
                    facets=info.facets,
                    search_text=" ".join([*names, *(member[1] for member in members)]).lower(),
                )
            )
        if changed:
            self._save_cache()
        return entries

    def _load_cache(self) -> dict[str, _DirInfo]:
        if self._cache_path is None or not self._cache_path.is_file():
            return {}
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict) or data.get("schema") != _CACHE_SCHEMA:
            return {}
        result = {}
        for key, item in (data.get("dirs") or {}).items():
            try:
                result[key] = _DirInfo(
                    tuple(tuple(part) for part in item["signature"]), str(item["fingerprint"]), dict(item["facets"])
                )
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def _save_cache(self) -> None:
        if self._cache_path is None or self._dirs is None:
            return
        payload = {
            "schema": _CACHE_SCHEMA,
            "dirs": {
                key: {"signature": info.signature, "fingerprint": info.fingerprint, "facets": info.facets}
                for key, info in self._dirs.items()
            },
        }
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._cache_path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temp.replace(self._cache_path)
        except OSError:
            pass  # 缓存写不进去只是下次慢一点


def iter_node_dirs(root: Path) -> Iterator[tuple[Path, tuple]]:
    """和 NodeWorkspace 相同的规则：含节点文件的目录就是一个节点，不再往下找。
    顺带返回节点文件的 (名字, 修改时间, 大小)；Windows 上 scandir 的 stat 不需要额外的系统调用。"""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                items = list(iterator)
        except OSError:
            continue
        files: list[tuple[str, int, int]] = []
        subdirs: list[str] = []
        for item in items:
            try:
                if item.is_dir():
                    subdirs.append(item.path)
                elif item.name in _WATCHED_FILES:
                    stat = item.stat()
                    files.append((item.name, stat.st_mtime_ns, stat.st_size))
            except OSError:
                continue
        if current != root and any(name in NODE_FILES for name, _, _ in files):
            yield current, tuple(sorted(files))
            continue
        stack.extend(Path(path) for path in sorted(subdirs, reverse=True))


def content_fingerprint(node_dir: Path) -> str:
    """节点内容的指纹：节点文件原文，去掉 meta.yaml / node.yaml 顶层随目录名变化的字段（含其下的缩进行）。"""
    digest = hashlib.sha1()
    for name in NODE_FILES:
        try:
            text = (node_dir / name).read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        text = text.replace("\r\n", "\n").strip()
        if name != "tags.txt":
            text = _strip_identity(text)
        digest.update(f"{name}\0{text}\0".encode("utf-8"))
    return digest.hexdigest()


def _strip_identity(text: str) -> str:
    """去掉身份字段；空行和行尾空白不算内容差异。"""
    kept: list[str] = []
    skipping = False
    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line:
            continue
        if not line[0].isspace() and not line.startswith("-"):
            skipping = line.split(":", 1)[0].strip() in _IDENTITY_KEYS
        if not skipping:
            kept.append(line)
    return "\n".join(kept)


def read_facets(node_dir: Path) -> dict[str, list[str]]:
    """classify.yaml 的分面值（小写）；subtype 按部位展开成一维。没有或读不了时为空。"""
    path = node_dir / "classify.yaml"
    try:
        data = yaml.load(path.read_text(encoding="utf-8-sig"), Loader=_LOADER) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    facets: dict[str, list[str]] = {}
    for name in FACET_FIELDS:
        value = data.get(name)
        if name == "subtype" and isinstance(value, dict):
            items = [item for values in value.values() if isinstance(values, list) for item in values]
        else:
            items = value if isinstance(value, list) else [value]
        cleaned = sorted(
            {str(item).strip().lower() for item in items if item not in (None, "") and not isinstance(item, (dict, list))}
        )
        if cleaned:
            facets[name] = cleaned
    return facets


def _facets_match(entry: LibraryEntry, chosen: dict[str, set[str]], *, skip: str | None = None) -> bool:
    """同一分面里任选一个命中即可，不同分面要同时满足（和随机节点池的过滤规则一致）。"""
    for name, values in chosen.items():
        if name == skip:
            continue
        if not values & set(entry.facets.get(name, [])):
            return False
    return True


def parse_facet_params(values: Iterable[str]) -> dict[str, list[str]]:
    """查询参数 facet=cast:solo&facet=pose:lying -> {"cast": ["solo"], "pose": ["lying"]}；未知分面忽略。"""
    result: dict[str, list[str]] = {}
    for raw in values:
        name, _, value = str(raw).partition(":")
        name = name.strip()
        value = value.strip().lower()
        if name in FACET_FIELDS and value:
            result.setdefault(name, []).append(value)
    return result
