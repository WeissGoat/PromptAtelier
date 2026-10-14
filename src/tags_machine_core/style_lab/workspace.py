from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from tags_machine_core.logging_config import get_logger

from .metadata import IMAGE_SUFFIXES, RECORD_VERSION, ImageRecord, build_image_record


logger = get_logger(__name__)

DATA_DIR_NAME = ".stylelab"
WORKSPACE_SCHEMA = "tags-machine-core.style-lab.workspace/v1"
INDEX_SCHEMA = "tags-machine-core.style-lab.index/v1"
RUN_SCHEMA = "tags-machine-core.style-lab.run/v1"


class WorkspaceInfo(BaseModel):
    schema_id: str = Field(default=WORKSPACE_SCHEMA, alias="schema")
    id: str
    name: str
    kind: Literal["folder", "files"]
    root: str
    data_dir: str
    scan_dirs: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    # 从工作区移除的图片（绝对路径）：扫描时跳过，原文件不动。
    excluded: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    last_opened_at: float = Field(default_factory=time.time)

    model_config = {"populate_by_name": True}


class WorkspaceIndex(BaseModel):
    schema_id: str = Field(default=INDEX_SCHEMA, alias="schema")
    scanned_at: float | None = None
    images: list[ImageRecord] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class WorkspaceStore:
    """工作区登记、图片索引和 run 记录。文件夹工作区的数据放在 <文件夹>/.stylelab/。"""

    def __init__(self, runtime_dir: str | Path):
        self.runtime_dir = Path(runtime_dir)
        self.registry_path = self.runtime_dir / "registry.json"
        self._lock = threading.RLock()
        self.lock = self._lock
        self._index_cache: dict[str, tuple[float, WorkspaceIndex]] = {}

    # ---- 登记 ----

    def list_workspaces(self) -> list[WorkspaceInfo]:
        items = [item for item in self._read_registry() if Path(item.data_dir).is_dir()]
        return sorted(items, key=lambda item: item.last_opened_at, reverse=True)

    def open_folder(self, root: str | Path, *, name: str | None = None) -> WorkspaceInfo:
        root_path = Path(root).expanduser()
        if not root_path.is_dir():
            raise FileNotFoundError(f"Folder not found: {root}")
        root_path = root_path.resolve()
        workspace_id = hashlib.sha1(str(root_path).lower().encode("utf-8")).hexdigest()[:10]
        data_dir = root_path / DATA_DIR_NAME
        existing = self._read_workspace_file(data_dir)
        if existing is not None:
            info = existing.model_copy(update={"last_opened_at": time.time()})
        else:
            origin = root_path / "origin"
            scan_dirs = [str(origin)] if origin.is_dir() else [str(root_path)]
            info = WorkspaceInfo(
                id=workspace_id,
                name=name or _default_name(root_path),
                kind="folder",
                root=str(root_path),
                data_dir=str(data_dir),
                scan_dirs=scan_dirs,
            )
        self._save_workspace(info)
        return info

    def open_files(self, files: list[str], *, name: str | None = None) -> WorkspaceInfo:
        paths = [Path(item).expanduser() for item in files if str(item).strip()]
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Files not found: {', '.join(missing[:5])}")
        workspace_id = uuid.uuid4().hex[:10]
        data_dir = self.runtime_dir / "workspaces" / workspace_id
        resolved = [str(path.resolve()) for path in paths]
        root = os.path.commonpath([str(Path(path).parent) for path in resolved]) if resolved else str(data_dir)
        info = WorkspaceInfo(
            id=workspace_id,
            name=name or f"图片组 {time.strftime('%Y-%m-%d %H:%M')}",
            kind="files",
            root=root,
            data_dir=str(data_dir),
            files=resolved,
        )
        self._save_workspace(info)
        return info

    def get(self, workspace_id: str) -> WorkspaceInfo:
        for item in self._read_registry():
            if item.id == workspace_id:
                stored = self._read_workspace_file(Path(item.data_dir))
                if stored is not None:
                    return stored
        raise KeyError(workspace_id)

    def rename(self, info: WorkspaceInfo, name: str) -> WorkspaceInfo:
        with self._lock:
            info = info.model_copy(update={"name": name})
            self._save_workspace(info)
            return info

    def remove(self, info: WorkspaceInfo) -> Path | None:
        """从工作区列表删掉。

        图片组的数据（拖进来的副本、配方、出图）只属于这个工作区，整个移到 runtime 下的 trash/，不直接删，
        需要时还能找回；文件夹工作区只从列表去掉，文件夹和其中的 .stylelab 都不动，重新打开就回来。
        返回移到 trash 的位置（文件夹工作区为 None）。
        """
        with self._lock:
            registry = [item for item in self._read_registry() if item.id != info.id]
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(
                self.registry_path,
                json.dumps(
                    {"workspaces": [item.model_dump(mode="json", by_alias=True) for item in registry]},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            self._index_cache.pop(info.id, None)
            data_dir = Path(info.data_dir)
            workspaces_dir = (self.runtime_dir / "workspaces").resolve()
            if info.kind != "files" or not data_dir.is_dir() or data_dir.resolve().parent != workspaces_dir:
                return None
            trash = self.runtime_dir / "trash" / f"{info.id}_{time.strftime('%Y%m%d_%H%M%S')}"
            trash.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(data_dir), str(trash))
            return trash

    def has_active_runs(self, info: WorkspaceInfo) -> bool:
        return any(run.get("status") in {"queued", "running", "cancelling"} for run in self.list_runs(info))

    def add_files(self, workspace_id: str, files: list[Path]) -> WorkspaceInfo:
        info = self.get(workspace_id)
        merged = list(dict.fromkeys([*info.files, *(str(path.resolve()) for path in files)]))
        info = info.model_copy(update={"files": merged})
        self._save_workspace(info)
        return info

    def uploads_dir(self, info: WorkspaceInfo) -> Path:
        return Path(info.data_dir) / "uploads"

    def remove_images(self, info: WorkspaceInfo, image_ids: list[str]) -> tuple[WorkspaceInfo, int]:
        """从工作区移除图片。拖进来的副本（uploads 里的）直接删掉；其余只记进 excluded，原文件不动。"""
        with self._lock:
            wanted = set(image_ids)
            paths = [Path(record.path) for record in self.load_index(info).images if record.id in wanted]
            uploads = self.uploads_dir(info).resolve()
            files = list(info.files)
            excluded = list(info.excluded)
            for path in paths:
                if path.resolve().parent == uploads:
                    path.unlink(missing_ok=True)
                elif str(path) in files:
                    files.remove(str(path))
                elif str(path) not in excluded:
                    excluded.append(str(path))
            info = info.model_copy(update={"files": files, "excluded": excluded})
            self._save_workspace(info)
            return info, len(paths)

    def restore_images(self, info: WorkspaceInfo) -> WorkspaceInfo:
        """恢复移除过的图片（只对 excluded 里的有效，删掉的上传副本回不来）。"""
        with self._lock:
            info = info.model_copy(update={"excluded": []})
            self._save_workspace(info)
            return info

    # ---- 索引 ----

    def load_index(self, info: WorkspaceInfo) -> WorkspaceIndex:
        path = Path(info.data_dir) / "index.json"
        if not path.is_file():
            return WorkspaceIndex()
        mtime = path.stat().st_mtime
        cached = self._index_cache.get(info.id)
        if cached and cached[0] == mtime:
            return cached[1]
        index = WorkspaceIndex.model_validate_json(path.read_text(encoding="utf-8"))
        self._index_cache[info.id] = (mtime, index)
        return index

    def scan(self, info: WorkspaceInfo) -> tuple[WorkspaceIndex, dict[str, int]]:
        """增量扫描：路径、大小、mtime_ns 都没变的图片沿用旧记录，不重新读文件。"""
        with self._lock:
            previous = {record.path: record for record in self.load_index(info).images}
            base = Path(info.root)
            records: list[ImageRecord] = []
            stats = {"total": 0, "reused": 0, "read": 0, "failed": 0}
            for path in self._iter_images(info):
                stats["total"] += 1
                try:
                    stat = path.stat()
                except OSError:
                    stats["failed"] += 1
                    continue
                old = previous.get(str(path))
                if (
                    old
                    and old.size_bytes == stat.st_size
                    and old.mtime_ns == stat.st_mtime_ns
                    and old.record_version == RECORD_VERSION
                ):
                    records.append(old)
                    stats["reused"] += 1
                    continue
                try:
                    records.append(build_image_record(path, base=base))
                    stats["read"] += 1
                except OSError as exc:
                    logger.warning("Style Lab failed to read %s: %s", path, exc)
                    stats["failed"] += 1
            records.sort(key=lambda record: ((record.post.date or "") if record.post else "", record.rel_path))
            index = WorkspaceIndex(scanned_at=time.time(), images=records)
            data_dir = Path(info.data_dir)
            data_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(data_dir / "index.json", index.model_dump_json(by_alias=True))
            self._index_cache.pop(info.id, None)
            return index, stats

    def needs_rescan(self, info: WorkspaceInfo) -> bool:
        """索引里有按旧解析规则读出的记录。"""
        return any(record.record_version != RECORD_VERSION for record in self.load_index(info).images)

    def find_image(self, info: WorkspaceInfo, image_id: str) -> ImageRecord:
        for record in self.load_index(info).images:
            if record.id == image_id:
                return record
        raise KeyError(image_id)

    def is_allowed_file(self, info: WorkspaceInfo, path: Path) -> bool:
        resolved = str(path)
        if any(record.path == resolved for record in self.load_index(info).images):
            return True
        runs_dir = (Path(info.data_dir) / "runs").resolve()
        try:
            return path.resolve().is_relative_to(runs_dir)
        except OSError:
            return False

    def _iter_images(self, info: WorkspaceInfo):
        seen: set[str] = set(info.excluded)
        if info.kind == "files":
            candidates = [Path(item) for item in info.files]
            uploads = self.uploads_dir(info)
            if uploads.is_dir():
                candidates.extend(sorted(uploads.iterdir()))
            for path in candidates:
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and str(path) not in seen:
                    seen.add(str(path))
                    yield path
            return
        visited_dirs: set[str] = set()
        for scan_dir in info.scan_dirs:
            for dirpath, dirnames, filenames in os.walk(scan_dir, followlinks=True):
                real = os.path.realpath(dirpath)
                if real in visited_dirs:
                    dirnames[:] = []
                    continue
                visited_dirs.add(real)
                dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
                for filename in sorted(filenames):
                    path = Path(dirpath) / filename
                    if path.suffix.lower() in IMAGE_SUFFIXES and str(path) not in seen:
                        seen.add(str(path))
                        yield path

    # ---- run ----

    def runs_dir(self, info: WorkspaceInfo) -> Path:
        return Path(info.data_dir) / "runs"

    def new_run_dir(self, info: WorkspaceInfo) -> tuple[str, Path]:
        run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        run_dir = self.runs_dir(info) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_id, run_dir

    def save_run(self, info: WorkspaceInfo, run: dict[str, Any]) -> None:
        with self._lock:
            run_dir = self.runs_dir(info) / str(run["id"])
            run_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(run_dir / "run.json", json.dumps(run, ensure_ascii=False, indent=2))

    def get_run(self, info: WorkspaceInfo, run_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[\w-]+", run_id):
            raise KeyError(run_id)
        path = self.runs_dir(info) / run_id / "run.json"
        # Windows 上读文件时另一个线程 replace 会失败，读写都在锁内。
        with self._lock:
            if not path.is_file():
                raise KeyError(run_id)
            return json.loads(path.read_text(encoding="utf-8"))

    def list_runs(
        self, info: WorkspaceInfo, *, image_id: str | None = None, recipe_id: str | None = None
    ) -> list[dict[str, Any]]:
        runs_dir = self.runs_dir(info)
        if not runs_dir.is_dir():
            return []
        runs: list[dict[str, Any]] = []
        for run_file in runs_dir.glob("*/run.json"):
            try:
                with self._lock:
                    run = json.loads(run_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if image_id and (run.get("source") or {}).get("image_id") != image_id:
                continue
            if recipe_id and (run.get("recipe") or {}).get("id") != recipe_id:
                continue
            runs.append(run)
        return sorted(runs, key=lambda run: run.get("created_at") or 0, reverse=True)

    # ---- 内部 ----

    def _read_registry(self) -> list[WorkspaceInfo]:
        if not self.registry_path.is_file():
            return []
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [WorkspaceInfo.model_validate(item) for item in data.get("workspaces", [])]

    def _read_workspace_file(self, data_dir: Path) -> WorkspaceInfo | None:
        path = data_dir / "workspace.json"
        if not path.is_file():
            return None
        return WorkspaceInfo.model_validate_json(path.read_text(encoding="utf-8"))

    def _save_workspace(self, info: WorkspaceInfo) -> None:
        with self._lock:
            data_dir = Path(info.data_dir)
            data_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(data_dir / "workspace.json", info.model_dump_json(by_alias=True, indent=2))
            registry = [item for item in self._read_registry() if item.id != info.id]
            registry.append(info)
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(
                self.registry_path,
                json.dumps(
                    {"workspaces": [item.model_dump(mode="json", by_alias=True) for item in registry]},
                    ensure_ascii=False,
                    indent=2,
                ),
            )


def _default_name(root: Path) -> str:
    # artist_parse/YYYYMMDD/<author> 用作者号 + 日期目录命名，其余用文件夹名。
    if re.fullmatch(r"\d{8}(_\d+)?", root.parent.name):
        return f"{root.name} · {root.parent.name}"
    return root.name


def _atomic_write(path: Path, text: str) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)
