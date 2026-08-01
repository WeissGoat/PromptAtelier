from __future__ import annotations

from pathlib import Path

from PIL import Image

from publishing_workspace.config import WorkspacePaths
from publishing_workspace.tasks import TaskPaths
from publishing_workspace.tasks.scanner import CurrentSelectionScanner, SelectionValidator


def _image(path: Path, color: str = "white") -> Path:
    Image.new("RGB", (8, 8), color=color).save(path)
    return path


def _task_paths(tmp_path: Path) -> TaskPaths:
    paths = TaskPaths.from_workspace(
        WorkspacePaths.from_root(tmp_path / "publish"),
        "task-001",
    )
    paths.ensure_layout()
    return paths


def test_scanner_uses_current_names_and_ignores_history(tmp_path: Path):
    task_paths = _task_paths(tmp_path)
    _image(task_paths.selection_dirs["all"] / "10_best.png", "red")
    _image(task_paths.selection_dirs["all"] / "2_best.png", "blue")
    (task_paths.history_dir / "old.json").write_text("{}", encoding="utf-8")

    selections = CurrentSelectionScanner().scan(task_paths, {".png"})

    assert [item.filename for item in selections["all"]] == [
        "2_best.png",
        "10_best.png",
    ]
    assert selections["post"] == []


def test_validator_warns_for_post_not_in_all(tmp_path: Path):
    task_paths = _task_paths(tmp_path)
    _image(task_paths.selection_dirs["all"] / "all.png", "red")
    _image(task_paths.selection_dirs["post"] / "different.png", "blue")

    selections = CurrentSelectionScanner().scan(task_paths, {".png"})
    warnings = SelectionValidator().validate(selections)

    assert any(item.code == "post_not_in_all" for item in warnings)


def test_validator_warns_for_cover_not_in_post_and_duplicate(tmp_path: Path):
    task_paths = _task_paths(tmp_path)
    source = _image(tmp_path / "source.png", "red")
    (task_paths.selection_dirs["all"] / "a.png").write_bytes(source.read_bytes())
    (task_paths.selection_dirs["all"] / "b.png").write_bytes(source.read_bytes())
    _image(task_paths.selection_dirs["cover"] / "cover.png", "blue")

    selections = CurrentSelectionScanner().scan(task_paths, {".png"})
    warnings = SelectionValidator().validate(selections)
    codes = {item.code for item in warnings}

    assert "duplicate_within_selection" in codes
    assert "cover_not_in_post" in codes
