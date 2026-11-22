"""出图历史：只读扫描输出目录，按批次列出图片。

- `outputs/` 和 `outputs/compares/` 下的每个子目录算一批（含 group_* 子目录里的图）；
- `outputs/` 根目录下的散图按创建日期归成"散图"批次，只读，不移动、不改名；
- `web.history_roots` 配置的额外目录（如定时跑图的 design/auto）下每个子目录也算一批，批次 ID 为 `@<序号>/<子目录>`；
- 以 `.` 开头的目录（如 `.web` 缓存）不扫。

目录内容按目录 mtime 缓存，PNG 摘要按文件 mtime / 大小缓存，重复刷新不会重读整个输出目录。
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from tags_machine_core.web.services.history_index import (
    HistoryIndex,
    IndexedImageEntry,
    NodeFilterSpec,
    read_png_text_chunks_fast,
)


IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
LOOSE_PREFIX = "loose/"
EXTRA_PREFIX = "@"
_RUN_KIND = re.compile(r"^(compare|random|sequential-all|sequential|primary|contract|studio)_")
_MAX_DEPTH = 3


def created_time(stat: os.stat_result) -> float:
    """文件 / 目录的创建时间；Windows 上 st_ctime 就是创建时间，其他系统退回 mtime。"""
    birth = getattr(stat, "st_birthtime", None)
    if birth:
        return float(birth)
    return float(stat.st_ctime if sys.platform == "win32" else stat.st_mtime)


@dataclass(frozen=True)
class _ImageFile:
    path: Path
    created_at: float
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class _DirListing:
    mtime_ns: int
    images: tuple[_ImageFile, ...]
    subdirs: tuple[Path, ...]


class OutputHistory:
    def __init__(
        self,
        output_root: str | Path,
        extra_roots: list[str | Path] | None = None,
        index_path: str | Path | None = None,
    ):
        self.root = Path(output_root).resolve()
        self.extra_roots = [Path(root).resolve() for root in extra_roots or []]
        self._dirs: dict[Path, _DirListing] = {}
        self._summaries: dict[tuple[Path, int, int], dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._index = HistoryIndex(Path(index_path) if index_path else None)
        self._sync_lock = threading.Lock()
        self._warmup_thread: threading.Thread | None = None
        self._last_sync_at: float = 0.0
        self._sync_ttl_seconds: float = 30.0

    def close(self) -> None:
        self._index.close()

    def start_background_warmup(self) -> None:
        """在后台线程自动扫描输出目录并补齐 SQLite 节点索引，不阻塞启动和页面访问。"""
        with self._sync_lock:
            if self._warmup_thread is not None and self._warmup_thread.is_alive():
                return
            thread = threading.Thread(
                target=self._run_warmup,
                name="history-warmup-worker",
                daemon=True,
            )
            self._warmup_thread = thread
            thread.start()

    def _run_warmup(self) -> None:
        try:
            entries = self._collect_all_entries()
            self._index.sync(entries, summarize_image, allow_background=True)
            self._last_sync_at = time.monotonic()
        except Exception:
            # 后台预热失败不影响主服务运行，下次查询会重试。
            pass

    def _ensure_synced(self, *, refresh: bool = False) -> None:
        now = time.monotonic()
        if not refresh and self._index.has_records():
            if self._last_sync_at > 0 and (now - self._last_sync_at) < self._sync_ttl_seconds:
                return
            # 已有持久化索引时直接先查库秒开，同时在后台增量同步新图。
            self.start_background_warmup()
            return
        entries = self._collect_all_entries()
        self._index.sync(entries, summarize_image)
        self._last_sync_at = time.monotonic()

    # ---- 批次列表 ----

    def list_runs(self) -> list[dict[str, Any]]:
        # 输出目录还没生成过图时可能不存在，额外目录照样列出
        runs = self._output_runs() + self._extra_runs()
        runs.sort(key=lambda run: run["created_at"], reverse=True)
        return runs

    def _output_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        root_listing = self._listing(self.root)
        if root_listing is None:
            return []
        for run_dir in self._run_dirs(root_listing):
            images = self._images_under(run_dir)
            if not images:
                continue
            stat = run_dir.stat()
            runs.append(self._run_entry(
                run_id=run_dir.relative_to(self.root).as_posix(),
                name=run_dir.name,
                kind=self._kind(run_dir.name),
                created_at=created_time(stat),
                images=images,
                path=run_dir,
            ))
        for day, images in self._loose_days(root_listing).items():
            runs.append(self._run_entry(
                run_id=f"{LOOSE_PREFIX}{day}",
                name=f"散图 · {day}",
                kind="loose",
                created_at=max(image.created_at for image in images),
                images=images,
                path=self.root,
            ))
        return runs

    def _extra_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for index, root in enumerate(self.extra_roots):
            listing = self._listing(root)
            if listing is None:
                continue
            for run_dir in listing.subdirs:
                images = self._images_under(run_dir)
                if not images:
                    continue
                runs.append(self._run_entry(
                    run_id=f"{EXTRA_PREFIX}{index}/{run_dir.name}",
                    name=f"{root.name} · {run_dir.name}",
                    kind=self._kind(run_dir.name),
                    created_at=created_time(run_dir.stat()),
                    images=images,
                    path=run_dir,
                ))
        return runs

    def run_images(self, run_id: str, *, offset: int = 0, limit: int = 300) -> dict[str, Any]:
        run_dir, images = self._resolve_run(run_id)
        if run_id.startswith(LOOSE_PREFIX):
            # 散图一天可能几百张，新的在前。
            images = sorted(images, key=lambda image: image.created_at, reverse=True)
        else:
            images = sorted(images, key=lambda image: (self._group_of(run_dir, image.path), image.created_at, image.path.name))
        page = images[offset: offset + limit]
        return {
            "schema": "tags-machine-core.web.history-run-images/v1",
            "run_id": run_id,
            "path": str(run_dir),
            "total": len(images),
            "offset": offset,
            "limit": limit,
            "images": [
                {
                    "path": str(image.path),
                    "filename": image.path.name,
                    "group": "" if run_id.startswith(LOOSE_PREFIX) else self._group_of(run_dir, image.path),
                    "created_at": image.created_at,
                    "size_bytes": image.size,
                    "info": self._summary(image),
                }
                for image in page
            ],
        }

    def search_images(
        self,
        *,
        node_filters: list[NodeFilterSpec] | None = None,
        q: str = "",
        backend: str = "",
        kind: str = "",
        run_id: str = "",
        offset: int = 0,
        limit: int = 200,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """跨批次按节点、关键字、后端、类型筛选历史出图。"""
        self._ensure_synced(refresh=refresh)
        return self._index.search(
            node_filters=node_filters,
            q=q,
            backend=backend,
            kind=kind,
            run_id=run_id,
            offset=offset,
            limit=limit,
        )

    def list_indexed_nodes(
        self,
        *,
        role: str = "",
        q: str = "",
        limit: int = 100,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """列出出图历史中出现过的节点及各自的图片数，供筛选器使用。"""
        self._ensure_synced(refresh=refresh)
        return self._index.list_nodes(role=role, q=q, limit=limit)

    def _collect_all_entries(self) -> list[IndexedImageEntry]:
        entries: list[IndexedImageEntry] = []
        root_listing = self._listing(self.root)
        if root_listing is not None:
            for run_dir in self._run_dirs(root_listing):
                images = self._images_under(run_dir)
                if not images:
                    continue
                run_id = run_dir.relative_to(self.root).as_posix()
                run_name = run_dir.name
                run_kind = self._kind(run_dir.name)
                for image in images:
                    entries.append(
                        IndexedImageEntry(
                            path=image.path,
                            run_id=run_id,
                            run_name=run_name,
                            run_kind=run_kind,
                            group_name=self._group_of(run_dir, image.path),
                            created_at=image.created_at,
                            mtime_ns=image.mtime_ns,
                            size_bytes=image.size,
                        )
                    )
            for day, images in self._loose_days(root_listing).items():
                run_id = f"{LOOSE_PREFIX}{day}"
                run_name = f"散图 · {day}"
                for image in images:
                    entries.append(
                        IndexedImageEntry(
                            path=image.path,
                            run_id=run_id,
                            run_name=run_name,
                            run_kind="loose",
                            group_name="",
                            created_at=image.created_at,
                            mtime_ns=image.mtime_ns,
                            size_bytes=image.size,
                        )
                    )
        for index, root in enumerate(self.extra_roots):
            listing = self._listing(root)
            if listing is None:
                continue
            for run_dir in listing.subdirs:
                images = self._images_under(run_dir)
                if not images:
                    continue
                run_id = f"{EXTRA_PREFIX}{index}/{run_dir.name}"
                run_name = f"{root.name} · {run_dir.name}"
                run_kind = self._kind(run_dir.name)
                for image in images:
                    entries.append(
                        IndexedImageEntry(
                            path=image.path,
                            run_id=run_id,
                            run_name=run_name,
                            run_kind=run_kind,
                            group_name=self._group_of(run_dir, image.path),
                            created_at=image.created_at,
                            mtime_ns=image.mtime_ns,
                            size_bytes=image.size,
                        )
                    )
        return entries

    # ---- 内部 ----

    def _run_entry(self, *, run_id: str, name: str, kind: str, created_at: float, images: list[_ImageFile], path: Path) -> dict[str, Any]:
        ordered = sorted(images, key=lambda image: image.created_at)
        groups = {image.path.parent for image in images}
        return {
            "id": run_id,
            "name": name,
            "kind": kind,
            "path": str(path),
            "created_at": created_at,
            "image_count": len(images),
            "group_count": len(groups),
            # 封面取最早和最新的几张，列表里不用再请求整批。
            "covers": [str(image.path) for image in (ordered[:3] if kind != "loose" else ordered[-3:][::-1])],
        }

    def _run_dirs(self, root_listing: _DirListing) -> list[Path]:
        run_dirs: list[Path] = []
        for subdir in root_listing.subdirs:
            if subdir.name == "compares":
                compares = self._listing(subdir)
                if compares is not None:
                    run_dirs.extend(compares.subdirs)
                continue
            run_dirs.append(subdir)
        return run_dirs

    def _loose_days(self, root_listing: _DirListing) -> dict[str, list[_ImageFile]]:
        days: dict[str, list[_ImageFile]] = {}
        for image in root_listing.images:
            day = datetime.fromtimestamp(image.created_at).strftime("%Y-%m-%d")
            days.setdefault(day, []).append(image)
        return days

    def _resolve_run(self, run_id: str) -> tuple[Path, list[_ImageFile]]:
        if run_id.startswith(LOOSE_PREFIX):
            day = run_id[len(LOOSE_PREFIX):]
            listing = self._listing(self.root)
            images = self._loose_days(listing).get(day) if listing else None
            if not images:
                raise FileNotFoundError(run_id)
            return self.root, images
        root = self.root
        if run_id.startswith(EXTRA_PREFIX):
            index, _, run_id = run_id[len(EXTRA_PREFIX):].partition("/")
            if not index.isdigit() or int(index) >= len(self.extra_roots):
                raise FileNotFoundError(run_id)
            root = self.extra_roots[int(index)]
        relative = Path(run_id)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise FileNotFoundError(run_id)
        run_dir = (root / relative).resolve()
        if not run_dir.is_relative_to(root) or not run_dir.is_dir():
            raise FileNotFoundError(run_id)
        return run_dir, self._images_under(run_dir)

    def _images_under(self, directory: Path, depth: int = 0) -> list[_ImageFile]:
        listing = self._listing(directory)
        if listing is None:
            return []
        images = list(listing.images)
        if depth + 1 < _MAX_DEPTH:
            for subdir in listing.subdirs:
                images.extend(self._images_under(subdir, depth + 1))
        return images

    def _listing(self, directory: Path) -> _DirListing | None:
        try:
            mtime_ns = directory.stat().st_mtime_ns
        except OSError:
            return None
        with self._lock:
            cached = self._dirs.get(directory)
        if cached is not None and cached.mtime_ns == mtime_ns:
            return cached
        images: list[_ImageFile] = []
        subdirs: list[Path] = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            subdirs.append(Path(entry.path))
                        elif entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_SUFFIXES:
                            stat = entry.stat()
                            images.append(_ImageFile(Path(entry.path), created_time(stat), stat.st_mtime_ns, stat.st_size))
                    except OSError:
                        continue
        except OSError:
            return None
        listing = _DirListing(mtime_ns=mtime_ns, images=tuple(images), subdirs=tuple(sorted(subdirs)))
        with self._lock:
            self._dirs[directory] = listing
        return listing

    def _group_of(self, run_dir: Path, image_path: Path) -> str:
        parent = image_path.parent
        return "" if parent == run_dir else parent.relative_to(run_dir).as_posix()

    def _kind(self, name: str) -> str:
        match = _RUN_KIND.match(name)
        return match.group(1) if match else "other"

    def _summary(self, image: _ImageFile) -> dict[str, Any]:
        key = (image.path, image.mtime_ns, image.size)
        with self._lock:
            cached = self._summaries.get(key)
        if cached is not None:
            return cached
        summary = summarize_image(image.path)
        with self._lock:
            self._summaries[key] = summary
        return summary


def _maybe_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _summary_node_entry(node: dict[str, Any]) -> dict[str, str] | None:
    raw_id = str(node.get("id") or "").strip()
    raw_ref = str(node.get("ref") or "").strip()
    name = PureWindowsPath(raw_id).name if raw_id else (PureWindowsPath(raw_ref).name if raw_ref else "")
    if not name and not raw_ref:
        return None
    entry: dict[str, str] = {"role": str(node.get("role") or ""), "name": name}
    if raw_ref:
        entry["ref"] = raw_ref
    return entry


def summarize_image(path: Path) -> dict[str, Any]:
    """网格里显示的几项：后端、seed、尺寸、节点名、耗时。读不出元数据时返回空摘要。"""
    summary: dict[str, Any] = {"backend": None, "seed": None, "width": None, "height": None, "nodes": [], "timing": None}
    if path.suffix.lower() != ".png":
        return summary
    try:
        chunks = read_png_text_chunks_fast(path)
    except (OSError, ValueError):
        return summary
    comment = _maybe_json_dict(chunks.get("Comment"))
    core = _maybe_json_dict(chunks.get("tags_machine_core"))
    render = core.get("render") if isinstance(core.get("render"), dict) else {}
    parameters = comment if comment else render
    seed = parameters.get("seed", render.get("seed"))
    nodes: list[dict[str, str]] = []
    for node in core.get("nodes") or []:
        if isinstance(node, dict):
            entry = _summary_node_entry(node)
            if entry is not None:
                nodes.append(entry)
    summary.update(
        backend=core.get("backend") or ("novelai" if comment else None),
        seed=seed if isinstance(seed, (int, str)) else None,
        width=parameters.get("width") or render.get("width"),
        height=parameters.get("height") or render.get("height"),
        nodes=nodes,
        timing=core.get("timing") if isinstance(core.get("timing"), dict) else None,
    )
    return summary
