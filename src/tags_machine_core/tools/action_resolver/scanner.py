from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .models import ScanIssue, ScannedSource, ScanResult


ARCHIVE_NAMES = (
    "render_request.json",
    "prompt_bundle.json",
    "generation_result.json",
)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class GeneratedActionInputScanner:
    def scan(self, inputs: Iterable[str | Path]) -> ScanResult:
        task_dirs: dict[str, Path] = {}
        image_paths: dict[str, Path] = {}
        discovery: list[tuple[str, str]] = []
        issues: list[ScanIssue] = []

        for raw in inputs:
            selected = Path(raw).expanduser()
            if not selected.exists():
                issues.append(ScanIssue(selected, f"输入路径不存在：{selected}"))
                continue
            try:
                selected = selected.resolve()
                if selected.is_file():
                    self._scan_file(selected, task_dirs, image_paths, discovery, issues)
                elif selected.is_dir():
                    self._scan_directory(selected, task_dirs, image_paths, discovery, issues)
                else:
                    issues.append(ScanIssue(selected, f"不支持的输入类型：{selected}"))
            except OSError as exc:
                issues.append(ScanIssue(selected, f"扫描输入失败：{exc}"))

        task_values = sorted(task_dirs.values(), key=lambda path: str(path).casefold())
        standalone_images = [
            path
            for path in image_paths.values()
            if not any(_is_relative_to(path, task_dir) for task_dir in task_values)
        ]
        standalone_images.sort(key=lambda path: str(path).casefold())
        valid_tasks = {str(path).casefold(): path for path in task_values}
        valid_images = {str(path).casefold(): path for path in standalone_images}
        sources: list[ScannedSource] = []
        for kind, key in discovery:
            path = valid_tasks.get(key) if kind == "task" else valid_images.get(key)
            if path is not None:
                sources.append(ScannedSource(kind=kind, path=path))
        return ScanResult(
            task_dirs=task_values,
            image_paths=standalone_images,
            sources=sources,
            issues=issues,
        )

    def _scan_file(
        self,
        path: Path,
        task_dirs: dict[str, Path],
        image_paths: dict[str, Path],
        discovery: list[tuple[str, str]],
        issues: list[ScanIssue],
    ) -> None:
        task_dir = find_task_dir(path)
        if task_dir is not None:
            _record_unique(task_dirs, task_dir, kind="task", discovery=discovery)
            return
        if path.suffix.casefold() in IMAGE_EXTENSIONS:
            _record_unique(image_paths, path, kind="image", discovery=discovery)
            return
        issues.append(ScanIssue(path, "文件不是新版任务归档或支持的图片"))

    def _scan_directory(
        self,
        path: Path,
        task_dirs: dict[str, Path],
        image_paths: dict[str, Path],
        discovery: list[tuple[str, str]],
        issues: list[ScanIssue],
    ) -> None:
        if is_task_dir(path):
            _record_unique(task_dirs, path, kind="task", discovery=discovery)
            return

        try:
            for root, directories, files in os.walk(path):
                current = Path(root)
                if any(name in files for name in ARCHIVE_NAMES):
                    _record_unique(task_dirs, current, kind="task", discovery=discovery)
                    directories[:] = []
                    continue
                for name in files:
                    image = current / name
                    if image.suffix.casefold() in IMAGE_EXTENSIONS:
                        _record_unique(image_paths, image, kind="image", discovery=discovery)
        except OSError as exc:
            issues.append(ScanIssue(path, f"扫描目录失败：{exc}"))


def is_task_dir(path: Path) -> bool:
    return any((path / name).is_file() for name in ARCHIVE_NAMES)


def find_task_dir(path: Path) -> Path | None:
    start = path if path.is_dir() else path.parent
    for candidate in (start, *start.parents):
        if is_task_dir(candidate):
            return candidate
    return None


def _record_unique(
    target: dict[str, Path],
    path: Path,
    *,
    kind: str,
    discovery: list[tuple[str, str]],
) -> None:
    resolved = path.resolve()
    key = str(resolved).casefold()
    if key in target:
        return
    target[key] = resolved
    discovery.append((kind, key))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
