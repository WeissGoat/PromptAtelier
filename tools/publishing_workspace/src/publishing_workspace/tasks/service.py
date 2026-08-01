from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import PublishingWorkspaceConfig, load_workspace
from ..inputs import InputContext, default_input_registry
from ..models import SelectionSet, utc_now_iso
from .models import (
    ImportMode,
    MaterializeResult,
    SelectionImportHistory,
    SelectionName,
    TaskConfig,
)
from .paths import TaskPaths
from .repository import TaskRepository
from .selection import SelectionMaterializer, SelectionSnapshotWriter


class TaskWorkflowService:
    def create(
        self,
        root: str | Path,
        task_id: str,
        *,
        title: str | None = None,
        candidates: str | Path | None = None,
        input_type: str | None = None,
        recursive: bool = False,
    ) -> TaskConfig:
        paths, workspace_config = load_workspace(root)
        task_paths = TaskPaths.from_workspace(paths, task_id)
        config = TaskRepository.create(task_paths, title=title)
        if candidates is not None:
            selection = self._load_selection(
                workspace_config,
                candidates,
                input_type=input_type,
                recursive=recursive,
            )
            result = SelectionMaterializer().materialize(
                selection,
                task_paths.selection_dirs["all"],
                mode="replace",
                image_extensions=set(workspace_config.image_extensions),
            )
            history = self._history(
                selection,
                selection_name="all",
                mode="replace",
                result=result,
            )
            TaskRepository.record_history(task_paths, history)
            SelectionSnapshotWriter().write_candidates(task_paths, selection)
        return config

    def import_selection(
        self,
        root: str | Path,
        task_id: str,
        selection_name: SelectionName,
        source: str | Path,
        *,
        input_type: str | None = None,
        recursive: bool = False,
        mode: ImportMode = "replace",
    ) -> SelectionImportHistory:
        paths, workspace_config = load_workspace(root)
        task_paths = TaskPaths.from_workspace(paths, task_id)
        TaskRepository.load(task_paths)
        selection = self._load_selection(
            workspace_config,
            source,
            input_type=input_type,
            recursive=recursive,
        )
        result = SelectionMaterializer().materialize(
            selection,
            task_paths.selection_dirs[selection_name],
            mode=mode,
            image_extensions=set(workspace_config.image_extensions),
        )
        history = self._history(
            selection,
            selection_name=selection_name,
            mode=mode,
            result=result,
        )
        TaskRepository.record_history(task_paths, history)
        return history

    def status(self, root: str | Path, task_id: str) -> dict[str, Any]:
        paths, workspace_config = load_workspace(root)
        task_paths = TaskPaths.from_workspace(paths, task_id)
        config = TaskRepository.load(task_paths)
        extensions = {item.casefold() for item in workspace_config.image_extensions}
        counts = {
            name: sum(
                1
                for path in directory.iterdir()
                if path.is_file() and path.suffix.casefold() in extensions
            )
            for name, directory in task_paths.selection_dirs.items()
        }
        history_count = sum(1 for path in task_paths.history_dir.glob("*.json"))
        build_count = sum(1 for path in task_paths.builds_root.iterdir() if path.is_dir())
        return {
            "task_id": config.task_id,
            "title": config.title,
            "task_yaml": str(task_paths.task_yaml),
            "selection_counts": counts,
            "history_count": history_count,
            "build_count": build_count,
            "status": _task_status(counts, build_count),
        }

    def build(self, root: str | Path, task_id: str):
        from ..packages.builder import PackageBuilder

        return PackageBuilder().build(root, task_id)

    @staticmethod
    def _load_selection(
        config: PublishingWorkspaceConfig,
        source: str | Path,
        *,
        input_type: str | None,
        recursive: bool,
    ) -> SelectionSet:
        return default_input_registry().load(
            source,
            input_type=input_type,
            context=InputContext(
                recursive=recursive,
                image_extensions=set(config.image_extensions),
            ),
        )

    @staticmethod
    def _history(
        selection: SelectionSet,
        *,
        selection_name: SelectionName,
        mode: ImportMode,
        result: MaterializeResult,
    ) -> SelectionImportHistory:
        return SelectionImportHistory(
            history_id=uuid4().hex,
            selection=selection_name,
            mode=mode,
            source_type=selection.source_type,
            source_ref=selection.source_ref,
            imported_at=utc_now_iso(),
            source_items=[item.model_dump(mode="json") for item in selection.items],
            materialized_files=result.materialized_files,
            skipped_duplicates=result.skipped_duplicates,
            warnings=result.warnings,
        )


def _task_status(counts: dict[str, int], build_count: int) -> str:
    if build_count:
        return "built"
    if counts["all"]:
        return "ready"
    return "selecting"
