from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from uuid import uuid4

from ..inputs.directory import natural_key
from ..logging import get_logger
from ..models import SelectionSet
from .models import ImportMode, MaterializeResult
from .naming import OutputNamePolicy
from .paths import TaskPaths


logger = get_logger(__name__)


class SelectionMaterializer:
    def __init__(
        self,
        name_policy: OutputNamePolicy | None = None,
        *,
        progress_every: int = 200,
    ):
        self.name_policy = name_policy or OutputNamePolicy()
        self.progress_every = max(1, progress_every)

    def materialize(
        self,
        selection: SelectionSet,
        target: Path,
        *,
        mode: ImportMode,
        image_extensions: set[str],
    ) -> MaterializeResult:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        supported = {extension.casefold() for extension in image_extensions}
        if mode == "replace":
            return self._replace(selection, target, supported)
        return self._append(selection, target, supported)

    def _replace(
        self,
        selection: SelectionSet,
        target: Path,
        supported: set[str],
    ) -> MaterializeResult:
        temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
        temporary.mkdir(parents=True, exist_ok=False)
        try:
            result = self._copy_items(
                selection,
                temporary,
                supported,
                existing_hashes=set(),
                start_index=1,
            )
            backup = target.parent / f".{target.name}.{uuid4().hex}.old"
            if target.exists():
                os.replace(target, backup)
            os.replace(temporary, target)
            if backup.exists():
                shutil.rmtree(backup)
            return result
        # Ctrl+C 属于 BaseException；也必须清理未提交的临时目录，避免下次任务看到残留文件。
        except BaseException:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def _append(
        self,
        selection: SelectionSet,
        target: Path,
        supported: set[str],
    ) -> MaterializeResult:
        target.mkdir(parents=True, exist_ok=True)
        existing_hashes = {
            _sha256(path)
            for path in _image_files(target, supported)
        }
        existing_names = {path.name for path in _image_files(target, supported)}
        start_index = len(existing_names) + 1
        return self._copy_items(
            selection,
            target,
            supported,
            existing_hashes=existing_hashes,
            start_index=start_index,
            used_names=existing_names,
        )

    def _copy_items(
        self,
        selection: SelectionSet,
        target: Path,
        supported: set[str],
        *,
        existing_hashes: set[str],
        start_index: int,
        used_names: set[str] | None = None,
    ) -> MaterializeResult:
        names = used_names if used_names is not None else set()
        input_hashes: set[str] = set()
        copied: list[str] = []
        warnings = list(selection.warnings)
        skipped_duplicates = 0
        next_index = start_index
        started_at = time.monotonic()
        for item_index, item in enumerate(selection.items, start=1):
            source = Path(item.resolved_path) if item.resolved_path else None
            if source is None or not source.is_file():
                warnings.append(f"图片不存在，未物化：{item.source_path}")
                continue
            if source.suffix.casefold() not in supported:
                warnings.append(f"图片扩展名不支持，未物化：{source}")
                continue
            digest = _sha256(source)
            if digest in existing_hashes or digest in input_hashes:
                skipped_duplicates += 1
                continue
            output_name = self.name_policy.make_name(
                next_index,
                source.name,
                names,
            )
            shutil.copy2(source, target / output_name)
            copied.append(output_name)
            input_hashes.add(digest)
            next_index += 1
            if (
                item_index % self.progress_every == 0
                or time.monotonic() - started_at >= 5
            ):
                logger.info(
                    "任务选择物化进度：processed=%s total=%s copied=%s skipped=%s",
                    item_index,
                    len(selection.items),
                    len(copied),
                    skipped_duplicates,
                )
                started_at = time.monotonic()
        logger.info(
            "任务选择物化完成：processed=%s total=%s copied=%s skipped=%s warnings=%s",
            len(selection.items),
            len(selection.items),
            len(copied),
            skipped_duplicates,
            len(warnings),
        )
        return MaterializeResult(
            materialized_files=copied,
            skipped_duplicates=skipped_duplicates,
            warnings=warnings,
        )


class SelectionSnapshotWriter:
    def write_candidates(
        self,
        paths: TaskPaths,
        selection: SelectionSet,
    ) -> tuple[Path, Path]:
        paths.ensure_layout()
        _write_json_atomic(
            paths.candidates_snapshot,
            selection.model_dump(mode="json", by_alias=True),
        )
        files = sorted(
            _image_files(paths.selection_dirs["all"], None),
            key=lambda path: natural_key(path.name),
        )
        payload = {
            "Format": "NeeView.Playlist/2.0.0",
            "Items": [{"Path": str(path.resolve())} for path in files],
        }
        _write_json_atomic(paths.candidates_playlist, payload)
        return paths.candidates_snapshot, paths.candidates_playlist


class SelectionHistoryWriter:
    def write(self, paths: TaskPaths, history) -> Path:
        return _record_history(paths, history)


def _image_files(directory: Path, extensions: set[str] | None) -> list[Path]:
    if not directory.is_dir():
        return []
    result = [path for path in directory.iterdir() if path.is_file()]
    if extensions is not None:
        normalized = {item.casefold() for item in extensions}
        result = [path for path in result if path.suffix.casefold() in normalized]
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _record_history(paths: TaskPaths, history) -> Path:
    paths.ensure_layout()
    timestamp = "".join(
        character for character in history.imported_at if character.isalnum() or character in "_-"
    )
    target = paths.history_dir / f"{timestamp}-{history.selection}-{history.history_id}.json"
    _write_json_atomic(target, history.model_dump(mode="json"))
    return target
