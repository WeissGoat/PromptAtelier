from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from publishing_workspace.config import WorkspacePaths, init_workspace
from publishing_workspace.packages import PackageBuilder
from publishing_workspace.png_metadata import read_png_text_chunks
from publishing_workspace.tasks import TaskConfig, TaskPaths, TaskRepository
from publishing_workspace.tasks.scanner import CurrentSelectionScanner, SelectionValidator


def _image(path: Path, color: str = "white") -> Path:
    Image.new("RGB", (8, 8), color=color).save(path)
    return path


def _image_with_text(path: Path) -> Path:
    image = Image.new("RGB", (8, 8), color="red")
    info = PngImagePlugin.PngInfo()
    info.add_text("prompt", "private")
    info.add_text("seed", "9")
    image.save(path, pnginfo=info)
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


def test_builder_creates_three_directories_and_optional_zip(tmp_path: Path):
    root = tmp_path / "publish"
    paths, _, _ = init_workspace(root)
    task_paths = TaskPaths.from_workspace(paths, "task-001")
    TaskRepository.create(task_paths, title="test")
    source = _image_with_text(tmp_path / "source.png")
    shutil.copy2(source, task_paths.selection_dirs["all"] / "0001_a.png")
    shutil.copy2(source, task_paths.selection_dirs["post"] / "manual_name.png")
    _image(task_paths.selection_dirs["cover"] / "cover.png", "blue")
    TaskRepository.save(
        task_paths,
        TaskConfig(
            task_id="task-001",
            title="test",
            packages={"zip": {"enabled": True}},
        ),
    )

    result = PackageBuilder().build(root, "task-001")

    assert result.output_paths["all"].is_dir()
    assert result.output_paths["post"].is_dir()
    assert result.output_paths["cover"].is_dir()
    assert result.archive_paths["all"].is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert manifest["processing_result"]["cache_hit"] >= 1
    assert (result.build_root / "selection_snapshot.json").is_file()
    assert read_png_text_chunks(result.output_paths["all"] / "0001_a.png") == {}
    with zipfile.ZipFile(result.archive_paths["all"]) as archive:
        assert archive.namelist() == ["0001_a.png"]


def test_failed_build_does_not_create_formal_build(tmp_path: Path):
    root = tmp_path / "publish"
    paths, _, _ = init_workspace(root)
    task_paths = TaskPaths.from_workspace(paths, "task-001")
    TaskRepository.create(task_paths, title="test")
    (task_paths.selection_dirs["all"] / "broken.png").write_bytes(b"not an image")

    with pytest.raises(ValueError, match="图片无法读取"):
        PackageBuilder().build(root, "task-001")

    assert list(task_paths.builds_root.iterdir()) == []
    assert (task_paths.selection_dirs["all"] / "broken.png").is_file()
