from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from publishing_workspace.cli import main


def test_publish_cli_init_and_empty_import(tmp_path: Path, capsys):
    root = tmp_path / "publish"
    source = tmp_path / "images"
    source.mkdir()

    assert main(["init", str(root)]) == 0
    init_result = json.loads(capsys.readouterr().out)
    assert init_result["created"] is True

    assert main(
        [
            "import",
            str(root),
            str(source),
            "--input-type",
            "directory",
        ]
    ) == 0
    import_result = json.loads(capsys.readouterr().out)
    assert import_result["total_items"] == 0
    assert import_result["unique_assets"] == 0


def test_cli_status_and_problems(tmp_path: Path, capsys):
    root = tmp_path / "publish"
    source = tmp_path / "images"
    source.mkdir()
    Image.new("RGB", (1, 1), "white").save(source / "a.png")

    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    assert main(["import", str(root), str(source), "--input-type", "directory"]) == 0
    imported = json.loads(capsys.readouterr().out)

    assert main(["status", str(root), imported["run_id"]]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["import_id"] == imported["run_id"]
    assert status["status"] == "completed"

    assert main(["problems", str(root), "--status", "open"]) == 0
    problems = json.loads(capsys.readouterr().out)
    assert problems["count"] == 0


def test_cli_retry_problems_requires_open_problem(tmp_path: Path, capsys):
    root = tmp_path / "publish"
    assert main(["init", str(root)]) == 0
    capsys.readouterr()

    assert main(["retry-problems", str(root), "--code", "empty_file"]) == 1
    assert "没有匹配的 open problem" in capsys.readouterr().err
