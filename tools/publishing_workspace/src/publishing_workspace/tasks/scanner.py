from __future__ import annotations

import hashlib
from pathlib import Path

from ..inputs.directory import natural_key
from .models import SelectionFile, SelectionName, SelectionSnapshot
from .paths import TaskPaths


class CurrentSelectionScanner:
    def scan(
        self,
        task_paths: TaskPaths,
        image_extensions: set[str],
    ) -> dict[SelectionName, list[SelectionFile]]:
        task_paths.ensure_layout()
        supported = {item.casefold() for item in image_extensions}
        return {
            selection: self._scan_one(
                task_paths,
                selection,
                supported,
            )
            for selection in ("all", "post", "cover")
        }

    @staticmethod
    def _scan_one(
        task_paths: TaskPaths,
        selection: SelectionName,
        supported: set[str],
    ) -> list[SelectionFile]:
        directory = task_paths.selection_dirs[selection]
        files = [
            path
            for path in directory.iterdir()
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.casefold() in supported
        ]
        files.sort(key=lambda path: natural_key(path.name))
        return [
            SelectionFile(
                selection=selection,
                filename=path.name,
                relative_path=str(path.relative_to(task_paths.task_root)),
                absolute_path=str(path.resolve()),
                content_sha256=_sha256(path),
            )
            for path in files
        ]

    def snapshot(
        self,
        task_paths: TaskPaths,
        image_extensions: set[str],
        *,
        build_id: str,
    ) -> SelectionSnapshot:
        selections = self.scan(task_paths, image_extensions)
        return SelectionSnapshot(build_id=build_id, selections=selections)


class SelectionValidator:
    def validate(
        self,
        selections: dict[SelectionName, list[SelectionFile]],
    ):
        from ..packages.models import WarningRecord

        warnings: list[WarningRecord] = []
        for selection, files in selections.items():
            seen: set[str] = set()
            for item in files:
                if item.content_sha256 in seen:
                    warnings.append(
                        WarningRecord(
                            code="duplicate_within_selection",
                            message=f"集合内存在重复图片：{item.filename}",
                            selection=selection,
                            filename=item.filename,
                        )
                    )
                seen.add(item.content_sha256)

        all_hashes = {item.content_sha256 for item in selections["all"]}
        post_hashes = {item.content_sha256 for item in selections["post"]}
        for item in selections["post"]:
            if item.content_sha256 not in all_hashes:
                warnings.append(
                    WarningRecord(
                        code="post_not_in_all",
                        message=f"post 图片不在 all 中：{item.filename}",
                        selection="post",
                        filename=item.filename,
                    )
                )
        for item in selections["cover"]:
            if item.content_sha256 not in post_hashes:
                warnings.append(
                    WarningRecord(
                        code="cover_not_in_post",
                        message=f"cover 图片不在 post 中：{item.filename}",
                        selection="cover",
                        filename=item.filename,
                    )
                )
        return warnings


_FILE_SHA256_CACHE: dict[tuple[str, int, int], str] = {}


def _sha256(path: Path) -> str:
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        cached = _FILE_SHA256_CACHE.get(key)
        if cached is not None:
            return cached
    except OSError:
        key = None

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    res = digest.hexdigest()
    if key is not None:
        _FILE_SHA256_CACHE[key] = res
    return res
