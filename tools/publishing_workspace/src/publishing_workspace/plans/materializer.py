from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..config import load_workspace
from ..models import AssetRecord, ImportedItem, SelectionSet
from ..tasks.repository import TaskRepository
from ..tasks.selection import SelectionMaterializer, SelectionSnapshotWriter
from ..tasks.paths import TaskPaths
from .models import InlineContent, ScheduleEntry


@dataclass
class MaterializedPlanTask:
    task_id: str
    task_root: Path
    temporary_root: Path
    task_paths: TaskPaths
    formal_builds_root: Path

    def cleanup(self) -> None:
        if self.temporary_root.exists():
            shutil.rmtree(self.temporary_root)


class InlineTaskMaterializer:
    def materialize(
        self,
        root: str | Path,
        *,
        plan_id: str,
        entry: ScheduleEntry,
        catalog,
        execution_id: str | None = None,
    ) -> MaterializedPlanTask:
        if not isinstance(entry.content, InlineContent):
            raise ValueError("只有 inline_selection 投稿可以物化")
        paths, config = load_workspace(root)
        execution_id = execution_id or uuid4().hex
        scope = _safe_segment(entry.entry_id)
        execution_scope = _safe_segment(execution_id)
        temporary_root = paths.cache / "monthly-plan" / plan_id / scope / execution_scope
        task_root = temporary_root / "task"
        task_id = f"monthly_{uuid4().hex[:16]}"
        task_paths = TaskPaths.from_task_root(paths, task_root, task_id=task_id)
        formal_builds_root = (
            paths.plans / plan_id / "executions" / scope / execution_scope / "builds"
        )
        formal_builds_root.mkdir(parents=True, exist_ok=True)
        if temporary_root.exists():
            raise FileExistsError(f"月度投稿临时目录已存在：{temporary_root}")

        assets = catalog.assets_for_import(entry.content.source_import_id)
        by_id = {asset.asset_id: asset for asset in assets}
        requested = {
            asset_id
            for selection in entry.content.sets.values()
            for asset_id in selection
        }
        missing = sorted(requested - set(by_id))
        if missing:
            raise ValueError(f"Catalog 中找不到 inline asset_id：{missing}")

        try:
            TaskRepository.create(task_paths, title=entry.title)
            for selection_name in ("all", "post", "cover"):
                selection = _selection_for(
                    entry.content.sets[selection_name],
                    by_id,
                )
                SelectionMaterializer().materialize(
                    selection,
                    task_paths.selection_dirs[selection_name],
                    mode="replace",
                    image_extensions=set(config.image_extensions),
                )
            SelectionSnapshotWriter().write_candidates(
                task_paths,
                _selection_for(entry.content.sets["all"], by_id),
            )
        except BaseException:
            if temporary_root.exists():
                shutil.rmtree(temporary_root)
            raise

        return MaterializedPlanTask(
            task_id=task_id,
            task_root=task_root,
            temporary_root=temporary_root,
            task_paths=task_paths,
            formal_builds_root=formal_builds_root,
        )


def _selection_for(asset_ids: list[str], assets: dict[str, AssetRecord]) -> SelectionSet:
    return SelectionSet(
        source_type="catalog",
        source_ref="monthly-plan",
        items=[
            ImportedItem(
                source_path=assets[asset_id].path,
                resolved_path=assets[asset_id].path,
                source_type="catalog",
                source_ref=asset_id,
                source_order=index,
                display_name=assets[asset_id].display_name,
            )
            for index, asset_id in enumerate(asset_ids)
        ],
    )


def _safe_segment(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    return text.strip(".") or "item"
