from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from publishing_workspace.cli import main


def _image(path: Path, color: str = "white") -> Path:
    Image.new("RGB", (8, 8), color=color).save(path)
    return path


def test_task_cli_create_then_status_reflects_manual_delete_and_rename(
    tmp_path: Path,
    capsys,
):
    root = tmp_path / "publish"
    source = tmp_path / "source"
    source.mkdir()
    _image(source / "01.png", "red")
    _image(source / "02.png", "blue")

    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    assert main(
        [
            "task",
            "create",
            str(root),
            "task-001",
            "--candidates",
            str(source),
            "--input-type",
            "directory",
        ]
    ) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["task_id"] == "task-001"

    all_dir = root / "tasks" / "task-001" / "selection" / "all"
    (all_dir / "0001_01.png").unlink()
    (all_dir / "0002_02.png").rename(all_dir / "0001_best.png")

    assert main(["task", "status", str(root), "task-001"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["selection_counts"] == {"all": 1, "post": 0, "cover": 0}
    assert status["status"] == "ready"


def test_task_cli_import_selection_records_history(tmp_path: Path, capsys):
    root = tmp_path / "publish"
    source = tmp_path / "source"
    source.mkdir()
    _image(source / "post.png", "green")

    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    assert main(["task", "create", str(root), "task-001"]) == 0
    capsys.readouterr()
    assert main(
        [
            "task",
            "import-selection",
            str(root),
            "task-001",
            "--set",
            "post",
            "--source",
            str(source),
            "--input-type",
            "directory",
        ]
    ) == 0
    history = json.loads(capsys.readouterr().out)
    assert history["selection"] == "post"
    assert history["materialized_files"] == ["0001_post.png"]
    assert len(list((root / "tasks/task-001/selection/history").glob("*.json"))) == 1
