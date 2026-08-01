from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from publishing_workspace.config import WorkspacePaths
from publishing_workspace.inputs import InputContext, default_input_registry
from publishing_workspace.tasks import SelectionMaterializer, TaskPaths


def _image(path: Path, color: str = "white") -> Path:
    Image.new("RGB", (8, 8), color=color).save(path)
    return path


def test_materializer_preserves_input_order_and_does_not_write_manifest(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _image(source / "10.png", "red")
    _image(source / "2.png", "blue")
    selection = default_input_registry().load(
        source,
        input_type="directory",
        context=InputContext(),
    )

    target = tmp_path / "task" / "selection" / "all"
    result = SelectionMaterializer().materialize(
        selection,
        target,
        mode="replace",
        image_extensions={".png"},
    )

    assert result.materialized_files == ["0001_2.png", "0002_10.png"]
    assert not (target / "selection.json").exists()


def test_append_deduplicates_by_content_and_keeps_existing_mtime(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "task" / "selection" / "all"
    source.mkdir()
    target.mkdir(parents=True)
    original = _image(source / "original.png", "red")
    existing = target / "0001_existing.png"
    shutil.copy2(original, existing)
    before = existing.stat().st_mtime_ns

    selection = default_input_registry().load(source, input_type="directory")
    result = SelectionMaterializer().materialize(
        selection,
        target,
        mode="append",
        image_extensions={".png"},
    )

    assert result.skipped_duplicates == 1
    assert existing.stat().st_mtime_ns == before


def test_task_paths_are_available_for_future_candidate_snapshots(tmp_path: Path):
    paths = TaskPaths.from_workspace(
        WorkspacePaths.from_root(tmp_path / "publish"),
        "task-001",
    )
    paths.ensure_layout()
    assert paths.candidates_snapshot.parent == paths.selection_root
