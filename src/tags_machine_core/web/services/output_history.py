"""出图历史：只读扫描输出目录，按批次列出图片。

- `outputs/` 和 `outputs/compares/` 下的每个子目录算一批（含 group_* 子目录里的图）；
- `outputs/` 根目录下的散图按创建日期归成"散图"批次，只读，不移动、不改名；
- 以 `.` 开头的目录（如 `.web` 缓存）不扫。

目录内容按目录 mtime 缓存，PNG 摘要按文件 mtime / 大小缓存，重复刷新不会重读整个输出目录。
"""

from __future__ import annotations

import os
import re
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from tags_machine_core.verification.image_params import read_image_parameters


IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
LOOSE_PREFIX = "loose/"
_RUN_KIND = re.compile(r"^(compare|random|sequential-all|sequential|primary)_")
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
    def __init__(self, output_root: str | Path):
        self.root = Path(output_root).resolve()
        self._dirs: dict[Path, _DirListing] = {}
        self._summaries: dict[tuple[Path, int, int], dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ---- 批次列表 ----

    def list_runs(self) -> list[dict[str, Any]]:
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
        runs.sort(key=lambda run: run["created_at"], reverse=True)
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
        relative = Path(run_id)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise FileNotFoundError(run_id)
        run_dir = (self.root / relative).resolve()
        if not run_dir.is_relative_to(self.root) or not run_dir.is_dir():
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


def summarize_image(path: Path) -> dict[str, Any]:
    """网格里显示的几项：后端、seed、尺寸、节点名、耗时。读不出元数据时返回空摘要。"""
    summary: dict[str, Any] = {"backend": None, "seed": None, "width": None, "height": None, "nodes": [], "timing": None}
    if path.suffix.lower() != ".png":
        return summary
    try:
        metadata = read_image_parameters(path)
    except (OSError, ValueError):
        return summary
    parameters = metadata.get("parameters") or {}
    core = metadata.get("png_text", {}).get("tags_machine_core")
    core = core if isinstance(core, dict) else {}
    render = core.get("render") if isinstance(core.get("render"), dict) else {}
    seed = parameters.get("seed", render.get("seed"))
    summary.update(
        backend=core.get("backend") or ("novelai" if parameters else None),
        seed=seed if isinstance(seed, (int, str)) else None,
        width=parameters.get("width") or render.get("width"),
        height=parameters.get("height") or render.get("height"),
        nodes=[
            {"role": str(node.get("role") or ""), "name": PureWindowsPath(str(node.get("id") or "")).name}
            for node in core.get("nodes") or []
            if isinstance(node, dict) and node.get("id")
        ],
        timing=core.get("timing") if isinstance(core.get("timing"), dict) else None,
    )
    return summary
