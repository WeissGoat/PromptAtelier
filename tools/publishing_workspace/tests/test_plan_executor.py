from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image

from publishing_workspace.config import init_workspace
from publishing_workspace.plans.executor import SubmissionExecutor
from publishing_workspace.plans.models import ScheduleEntry, TaskContent
from publishing_workspace.plans.notifier import NotificationResult
from publishing_workspace.plans.service import ScheduleService
from publishing_workspace.tasks.paths import TaskPaths
from publishing_workspace.tasks.repository import TaskRepository


def create_task(root: Path, task_id: str, *, broken: bool = False) -> Path:
    paths, _, _ = init_workspace(root)
    task_paths = TaskPaths.from_workspace(paths, task_id)
    TaskRepository.create(task_paths, title=task_id)
    image_path = task_paths.selection_dirs["all"] / "0001.png"
    image_path.write_bytes(b"broken" if broken else b"")
    if not broken:
        Image.new("RGB", (8, 8), "red").save(image_path)
    task_paths.selection_dirs["post"].mkdir(parents=True, exist_ok=True)
    post_path = task_paths.selection_dirs["post"] / "0001.png"
    if broken:
        post_path.write_bytes(b"broken")
    else:
        Image.new("RGB", (8, 8), "blue").save(post_path)
    return image_path


def entry(entry_id: str, task_id: str, scheduled_at: str) -> ScheduleEntry:
    return ScheduleEntry(
        entry_id=entry_id,
        scheduled_at=datetime.fromisoformat(scheduled_at),
        title=task_id,
        content=TaskContent(task_id=task_id),
    )


class RecordingNotifier:
    def __init__(self, result: NotificationResult):
        self.result = result
        self.events = []

    def notify(self, event):
        self.events.append(event)
        return self.result


def locked_plan(root: Path, entries: list[ScheduleEntry]):
    service = ScheduleService()
    service.create_plan(root, "2026-09")
    for item in entries:
        service.add_entry(root, "2026-09", item)
    service.lock(root, "2026-09")


def test_run_due_continues_after_one_entry_fails(tmp_path: Path):
    init_workspace(tmp_path)
    create_task(tmp_path, "bad-task")
    create_task(tmp_path, "good-task")
    bad_source = tmp_path / "tasks" / "bad-task" / "selection" / "all" / "0001.png"
    bad_source.write_bytes(b"not-an-image")
    locked_plan(
        tmp_path,
        [
            entry("bad-entry", "bad-task", "2026-09-05T20:00:00+08:00"),
            entry("good-entry", "good-task", "2026-09-05T21:00:00+08:00"),
        ],
    )

    records = SubmissionExecutor().run_due(
        tmp_path,
        now=datetime.fromisoformat("2026-09-05T22:00:00+08:00"),
    )

    assert [record.status for record in records] == ["failed", "completed"]
    assert records[0].error
    assert records[1].build_id
    assert (tmp_path / "tasks" / "good-task" / "builds").is_dir()


def test_run_due_executes_draft_plan(tmp_path: Path):
    init_workspace(tmp_path)
    create_task(tmp_path, "draft-task")
    service = ScheduleService()
    service.create_plan(tmp_path, "2026-09")
    service.add_entry(
        tmp_path,
        "2026-09",
        entry("draft-entry", "draft-task", "2026-09-05T20:00:00+08:00"),
    )

    records = SubmissionExecutor().run_due(
        tmp_path,
        now=datetime.fromisoformat("2026-09-05T22:00:00+08:00"),
    )

    assert [record.status for record in records] == ["completed"]


def test_run_due_is_idempotent_after_success(tmp_path: Path):
    init_workspace(tmp_path)
    create_task(tmp_path, "good-task")
    locked_plan(
        tmp_path,
        [entry("good-entry", "good-task", "2026-09-05T20:00:00+08:00")],
    )
    executor = SubmissionExecutor()
    now = datetime.fromisoformat("2026-09-05T22:00:00+08:00")

    first = executor.run_due(tmp_path, now=now)
    second = executor.run_due(tmp_path, now=now)

    assert len(first) == 1
    assert first[0].status == "completed"
    assert second == []


def test_notification_failure_does_not_fail_build(tmp_path: Path):
    init_workspace(tmp_path)
    create_task(tmp_path, "good-task")
    locked_plan(
        tmp_path,
        [entry("good-entry", "good-task", "2026-09-05T20:00:00+08:00")],
    )
    notifier = RecordingNotifier(
        NotificationResult(status="failed", message="test notification error")
    )

    records = SubmissionExecutor(notifier=notifier).run_due(
        tmp_path,
        now=datetime.fromisoformat("2026-09-05T22:00:00+08:00"),
    )

    assert records[0].status == "completed"
    assert records[0].notification_status == "failed"
    assert len(notifier.events) == 1


def test_retry_only_reexecutes_failed_entry(tmp_path: Path):
    init_workspace(tmp_path)
    create_task(tmp_path, "good-task")
    locked_plan(
        tmp_path,
        [entry("good-entry", "good-task", "2026-09-05T20:00:00+08:00")],
    )
    executor = SubmissionExecutor()
    first = executor.run_due(
        tmp_path,
        now=datetime.fromisoformat("2026-09-05T22:00:00+08:00"),
    )
    assert first[0].status == "completed"

    assert executor.retry(tmp_path, "2026-09", "good-entry") is None
