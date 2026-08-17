from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image

from publishing_workspace.catalog.repository import CatalogRepository
from publishing_workspace.config import init_workspace
from publishing_workspace.plans.executor import SubmissionExecutor
from publishing_workspace.plans.models import InlineContent, ScheduleEntry, TaskContent
from publishing_workspace.plans.service import ScheduleService
from publishing_workspace.tasks.paths import TaskPaths
from publishing_workspace.tasks.repository import TaskRepository


def image(path: Path, color: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color).save(path)
    return path


def seed_task(root: Path, task_id: str) -> None:
    paths, _, _ = init_workspace(root)
    task_paths = TaskPaths.from_workspace(paths, task_id)
    TaskRepository.create(task_paths, title="已有图集")
    image(task_paths.selection_dirs["all"] / "0001.png", "red")
    image(task_paths.selection_dirs["post"] / "0001.png", "blue")


def import_assets(root: Path) -> tuple[str, list[str]]:
    paths, _, _ = init_workspace(root)
    source = root / "source"
    for index, color in enumerate(("red", "green", "blue"), start=1):
        image(source / f"asset-{index}.png", color)
    from publishing_workspace.service import PublishingService

    summary = PublishingService().import_source(root, source, input_type="directory")
    catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
    assets = catalog.assets_for_import(summary.import_id)
    return summary.import_id, [asset.asset_id for asset in assets]


def test_monthly_calendar_end_to_end_small_business_case(tmp_path: Path):
    root = tmp_path / "publishing"
    init_workspace(root)
    import_id, asset_ids = import_assets(root)
    seed_task(root, "existing-album")

    service = ScheduleService()
    service.create_plan(root, "2026-09", default_import_id=import_id)
    service.add_entry(
        root,
        "2026-09",
        ScheduleEntry(
            entry_id="inline-entry",
            scheduled_at=datetime.fromisoformat("2026-09-05T20:00:00+08:00"),
            title="散图投稿",
            content=InlineContent(
                source_import_id=import_id,
                sets={
                    "all": [asset_ids[2], asset_ids[0], asset_ids[1]],
                    "post": [asset_ids[1], asset_ids[0]],
                    "cover": [asset_ids[2]],
                },
            ),
        ),
    )
    service.add_entry(
        root,
        "2026-09",
        ScheduleEntry(
            entry_id="task-entry",
            scheduled_at=datetime.fromisoformat("2026-09-05T21:00:00+08:00"),
            title="已有图集",
            content=TaskContent(task_id="existing-album"),
        ),
    )
    service.add_entry(
        root,
        "2026-09",
        ScheduleEntry(
            entry_id="inline-late-entry",
            scheduled_at=datetime.fromisoformat("2026-09-06T20:00:00+08:00"),
            title="补充散图",
            content=InlineContent(
                source_import_id=import_id,
                sets={"all": [asset_ids[0]], "post": [asset_ids[0]], "cover": []},
            ),
        ),
    )
    plan = service.lock(root, "2026-09")
    assert plan.status == "locked"

    now = datetime.fromisoformat("2026-09-06T21:00:00+08:00")
    first = SubmissionExecutor().run_due(root, now=now)
    second = SubmissionExecutor().run_due(root, now=now)

    assert [record.status for record in first] == ["completed", "completed", "completed"]
    assert second == []
    assert all(record.build_id for record in first)
    execution_root = root / "plans" / "2026-09" / "executions"
    assert list(execution_root.rglob("build_manifest.json"))
    assert not list((root / "workspace" / "cache" / "monthly-plan").glob("**/task"))
