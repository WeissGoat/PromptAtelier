from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from publishing_workspace.cli import main
from publishing_workspace.config import init_workspace
from publishing_workspace.tasks.paths import TaskPaths
from publishing_workspace.tasks.repository import TaskRepository


def make_entry(path: Path, *, entry_id: str = "entry-1", task_id: str = "task-1") -> None:
    path.write_text(
        json.dumps(
            {
                "entry_id": entry_id,
                "scheduled_at": "2026-09-05T20:00:00+08:00",
                "title": "测试投稿",
                "content": {"kind": "task", "task_id": task_id},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def make_task(root: Path, task_id: str = "task-1") -> None:
    paths, _, _ = init_workspace(root)
    task_paths = TaskPaths.from_workspace(paths, task_id)
    TaskRepository.create(task_paths, title=task_id)
    Image.new("RGB", (8, 8), "red").save(task_paths.selection_dirs["all"] / "0001.png")
    Image.new("RGB", (8, 8), "blue").save(task_paths.selection_dirs["post"] / "0001.png")


def test_schedule_cli_create_add_move_and_show(tmp_path: Path, capsys):
    init_workspace(tmp_path)
    entry_path = tmp_path / "entry.json"
    make_entry(entry_path)

    assert main(["schedule", "create", str(tmp_path), "2026-09"]) == 0
    json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                "schedule",
                "add-entry",
                str(tmp_path),
                "2026-09",
                "--entry-json",
                str(entry_path),
            ]
        )
        == 0
    )
    added = json.loads(capsys.readouterr().out)
    assert added["revision"] == 2

    assert (
        main(
            [
                "schedule",
                "move-date",
                str(tmp_path),
                "2026-09",
                "entry-1",
                "2026-09-08",
                "--expected-revision",
                "2",
            ]
        )
        == 0
    )
    moved = json.loads(capsys.readouterr().out)
    assert moved["entries"][0]["scheduled_at"].startswith("2026-09-08")

    assert main(["schedule", "show", str(tmp_path), "2026-09"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["entries"][0]["entry_id"] == "entry-1"


def test_schedule_cli_lock_and_run_due(tmp_path: Path, capsys):
    make_task(tmp_path)
    entry_path = tmp_path / "entry.json"
    make_entry(entry_path)
    main(["schedule", "create", str(tmp_path), "2026-09"])
    capsys.readouterr()
    main(
        [
            "schedule",
            "add-entry",
            str(tmp_path),
            "2026-09",
            "--entry-json",
            str(entry_path),
        ]
    )
    capsys.readouterr()

    assert main(["schedule", "lock", str(tmp_path), "2026-09", "--expected-revision", "2"]) == 0
    locked = json.loads(capsys.readouterr().out)
    assert locked["status"] == "locked"

    assert (
        main(
            [
                "schedule",
                "run-due",
                str(tmp_path),
                "--now",
                "2026-09-05T22:00:00+08:00",
            ]
        )
        == 0
    )
    records = json.loads(capsys.readouterr().out)
    assert records[0]["status"] == "completed"
    assert records[0]["build_id"]
