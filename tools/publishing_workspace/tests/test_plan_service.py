from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from PIL import Image

from publishing_workspace.config import init_workspace
from publishing_workspace.plans.models import ScheduleEntry, TaskContent
from publishing_workspace.plans.service import (
    PlanLockedError,
    PlanValidationError,
    ScheduleService,
)
from publishing_workspace.tasks.paths import TaskPaths
from publishing_workspace.tasks.repository import TaskRepository


def entry_at(value: str, entry_id: str = "entry-1") -> ScheduleEntry:
    return ScheduleEntry(
        entry_id=entry_id,
        scheduled_at=datetime.fromisoformat(value),
        title=entry_id,
        content=TaskContent(task_id="task-1"),
    )


def create_task(root: Path, *, post_count: int = 1) -> None:
    paths, _, _ = init_workspace(root)
    task_paths = TaskPaths.from_workspace(paths, "task-1")
    TaskRepository.create(task_paths, title="测试任务")
    for index in range(post_count):
        Image.new("RGB", (8, 8), (index, 0, 0)).save(
            task_paths.selection_dirs["post"] / f"{index + 1:04d}.png"
        )


def test_move_entry_date_preserves_time(tmp_path: Path):
    create_task(tmp_path)
    service = ScheduleService()
    service.create_plan(tmp_path, "2026-09")
    service.add_entry(tmp_path, "2026-09", entry_at("2026-09-05T20:00:00+08:00"))

    plan = service.move_entry_date(
        tmp_path,
        "2026-09",
        "entry-1",
        date(2026, 9, 8),
    )

    assert plan.entries[0].scheduled_at.isoformat() == "2026-09-08T20:00:00+08:00"


def test_locked_plan_rejects_edit(tmp_path: Path):
    create_task(tmp_path)
    service = ScheduleService()
    service.create_plan(tmp_path, "2026-09")
    service.add_entry(tmp_path, "2026-09", entry_at("2026-09-05T20:00:00+08:00"))
    service.lock(tmp_path, "2026-09")

    with pytest.raises(PlanLockedError):
        service.delete_entry(tmp_path, "2026-09", "entry-1")


def test_lock_requires_post_images(tmp_path: Path):
    create_task(tmp_path, post_count=0)
    service = ScheduleService()
    service.create_plan(tmp_path, "2026-09")
    service.add_entry(tmp_path, "2026-09", entry_at("2026-09-05T20:00:00+08:00"))

    with pytest.raises(PlanValidationError, match="post"):
        service.lock(tmp_path, "2026-09")


def test_same_time_entries_are_allowed(tmp_path: Path, caplog):
    create_task(tmp_path)
    service = ScheduleService()
    service.create_plan(tmp_path, "2026-09")
    service.add_entry(tmp_path, "2026-09", entry_at("2026-09-05T20:00:00+08:00"))
    service.add_entry(
        tmp_path,
        "2026-09",
        entry_at("2026-09-05T20:00:00+08:00", entry_id="entry-2"),
    )

    assert len(service.get_plan(tmp_path, "2026-09").entries) == 2
    assert any("同一时间存在多条投稿" in record.message for record in caplog.records)


def test_revision_conflict_is_propagated(tmp_path: Path):
    create_task(tmp_path)
    service = ScheduleService()
    service.create_plan(tmp_path, "2026-09")
    service.add_entry(
        tmp_path,
        "2026-09",
        entry_at("2026-09-05T20:00:00+08:00"),
        expected_revision=1,
    )

    with pytest.raises(RuntimeError, match="revision"):
        service.delete_entry(
            tmp_path,
            "2026-09",
            "entry-1",
            expected_revision=1,
        )
