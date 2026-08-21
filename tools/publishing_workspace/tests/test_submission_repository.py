from __future__ import annotations

from pathlib import Path

import pytest

from publishing_workspace.config import init_workspace
from publishing_workspace.plans.models import MonthlyPlan, ScheduleEntry, TaskContent
from publishing_workspace.plans.paths import PlanPaths
from publishing_workspace.plans.repository import PlanRepository
from publishing_workspace.submissions.models import (
    Submission,
    SubmissionRevisionConflictError,
)
from publishing_workspace.submissions.repository import SubmissionRepository
from publishing_workspace.tasks.paths import TaskPaths
from publishing_workspace.tasks.repository import TaskRepository


def test_submission_repository_save_and_load(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    task_paths = TaskPaths.from_workspace(paths, "task-1")
    task_paths.ensure_layout()

    assert SubmissionRepository.load(task_paths) is None

    submission = Submission(
        submission_id="task-1",
        task_id="task-1",
        title="初始投稿",
        sets={"all": ["sha256:a", "sha256:b"]},
    )
    saved = SubmissionRepository.save(task_paths, submission)
    assert saved.revision == 1

    loaded = SubmissionRepository.load(task_paths)
    assert loaded is not None
    assert loaded.submission_id == "task-1"
    assert loaded.title == "初始投稿"
    assert loaded.sets["all"] == ["sha256:a", "sha256:b"]
    assert loaded.sets["post"] == ["sha256:a", "sha256:b"]
    assert loaded.sets["cover"] == ["sha256:a"]


def test_submission_repository_rejects_revision_conflict(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    task_paths = TaskPaths.from_workspace(paths, "task-1")
    task_paths.ensure_layout()

    submission = Submission(
        submission_id="task-1",
        task_id="task-1",
        title="初始投稿",
        sets={"all": ["sha256:a"]},
    )
    SubmissionRepository.save(task_paths, submission)

    with pytest.raises(SubmissionRevisionConflictError):
        SubmissionRepository.save(
            task_paths,
            submission.model_copy(update={"title": "冲突修改"}),
            expected_revision=99,
        )


def test_submission_repository_update_last_export(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    task_paths = TaskPaths.from_workspace(paths, "task-1")
    task_paths.ensure_layout()

    submission = Submission(
        submission_id="task-1",
        task_id="task-1",
        title="投稿",
        sets={"all": ["sha256:a"]},
    )
    SubmissionRepository.save(task_paths, submission)

    SubmissionRepository.update_last_export(
        task_paths,
        build_id="build-001",
        output_dir=str(task_paths.builds_root / "build-001"),
    )

    loaded = SubmissionRepository.load(task_paths)
    assert loaded is not None
    assert loaded.last_export is not None
    assert loaded.last_export["build_id"] == "build-001"


def test_submission_repository_list_summarizes_tasks_and_plans(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)

    # 1. 带有 submission.yaml 的任务
    task1_paths = TaskPaths.from_workspace(paths, "task-1")
    TaskRepository.create(task1_paths, title="任务一")
    sub1 = Submission(
        submission_id="task-1",
        task_id="task-1",
        title="任务一",
        sets={"all": ["sha256:a", "sha256:b"]},
    )
    SubmissionRepository.save(task1_paths, sub1)

    # 2. 只有 task.yaml 的兼容旧任务
    task2_paths = TaskPaths.from_workspace(paths, "task-2")
    TaskRepository.create(task2_paths, title="旧任务二")
    (task2_paths.selection_dirs["all"] / "sample.png").write_bytes(b"dummy image")

    # 3. 创建关联 task-1 的月度计划
    plan_paths = PlanPaths.from_workspace(paths, "2026-08")
    plan = PlanRepository().create(plan_paths)
    plan.entries.append(
        ScheduleEntry(
            entry_id="entry-1",
            scheduled_at="2026-08-25T12:00:00+08:00",
            title="任务一排期",
            content=TaskContent(task_id="task-1"),
        )
    )
    PlanRepository().save(plan_paths, plan, expected_revision=1)

    summaries = SubmissionRepository.list(paths)
    assert len(summaries) == 2

    s1 = next(s for s in summaries if s.task_id == "task-1")
    assert s1.title == "任务一"
    assert s1.counts["all"] == 2
    assert len(s1.scheduled_entries) == 1
    assert s1.scheduled_entries[0].plan_id == "2026-08"

    s2 = next(s for s in summaries if s.task_id == "task-2")
    assert s2.title == "旧任务二"
    assert s2.counts["all"] == 1
    assert any("缺少 submission.yaml" in w for w in s2.warnings)
