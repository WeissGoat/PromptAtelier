from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from publishing_workspace.config import WorkspacePaths, init_workspace
from publishing_workspace.plans.models import (
    ExecutionRecord,
    InlineContent,
    MonthlyPlan,
    ScheduleEntry,
    TaskContent,
)
from publishing_workspace.plans.paths import PlanPaths
from publishing_workspace.plans.repository import (
    PlanRepository,
    PlanRevisionConflictError,
)


def entry_at(value: str, entry_id: str = "entry-1") -> ScheduleEntry:
    return ScheduleEntry(
        entry_id=entry_id,
        scheduled_at=datetime.fromisoformat(value),
        title="测试投稿",
        content=TaskContent(task_id="task-1"),
    )


def test_inline_content_defaults_to_empty_selection_sets():
    content = InlineContent()

    assert content.sets == {"all": [], "post": [], "cover": []}


def test_plan_accepts_task_and_inline_content():
    plan = MonthlyPlan(
        plan_id="2026-09",
        month="2026-09",
        entries=[
            entry_at("2026-09-05T20:00:00+08:00"),
            ScheduleEntry(
                entry_id="entry-2",
                scheduled_at=datetime.fromisoformat("2026-09-06T12:00:00+08:00"),
                title="散图投稿",
                content=InlineContent(
                    source_import_id="import-1",
                    sets={"all": ["sha256:a"], "post": ["sha256:a"], "cover": []},
                ),
            ),
        ],
    )

    assert plan.status == "draft"
    assert isinstance(plan.entries[0].content, TaskContent)
    assert isinstance(plan.entries[1].content, InlineContent)


def test_plan_rejects_entry_outside_month():
    with pytest.raises(ValueError, match="scheduled_at"):
        MonthlyPlan(
            plan_id="2026-09",
            month="2026-09",
            entries=[entry_at("2026-10-01T12:00:00+08:00")],
        )


def test_plan_rejects_duplicate_entry_id():
    with pytest.raises(ValueError, match="entry_id"):
        MonthlyPlan(
            plan_id="2026-09",
            month="2026-09",
            entries=[
                entry_at("2026-09-01T12:00:00+08:00"),
                entry_at("2026-09-02T12:00:00+08:00"),
            ],
        )


def test_plan_repository_round_trip_and_revision(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    plan_paths = PlanPaths.from_workspace(paths, "2026-09")
    repository = PlanRepository()

    created = repository.create(plan_paths, default_import_id="import-1")
    saved = repository.save(
        plan_paths,
        created.model_copy(update={"entries": [entry_at("2026-09-05T20:00:00+08:00")]}),
        expected_revision=created.revision,
    )
    loaded = repository.load(plan_paths)

    assert saved.revision == 2
    assert loaded.default_import_id == "import-1"
    assert loaded.entries[0].entry_id == "entry-1"


def test_plan_repository_rejects_stale_revision(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    plan_paths = PlanPaths.from_workspace(paths, "2026-09")
    repository = PlanRepository()
    created = repository.create(plan_paths)

    with pytest.raises(PlanRevisionConflictError):
        repository.save(
            plan_paths,
            created.model_copy(update={"revision": 99}),
            expected_revision=0,
        )


def test_execution_record_round_trip(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    plan_paths = PlanPaths.from_workspace(paths, "2026-09")
    repository = PlanRepository()
    repository.create(plan_paths)
    record = ExecutionRecord(
        execution_id="execution-1",
        entry_id="entry-1",
        plan_revision=1,
        scheduled_at=datetime.fromisoformat("2026-09-05T20:00:00+08:00"),
        status="completed",
        build_id="build-1",
    )

    repository.save_execution(plan_paths, record)

    assert repository.load_execution(plan_paths, "execution-1").build_id == "build-1"
