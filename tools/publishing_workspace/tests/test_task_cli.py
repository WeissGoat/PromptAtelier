from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, PngImagePlugin

from publishing_workspace.cli import main
from publishing_workspace.png_metadata import read_png_text_chunks


def _image(path: Path, color: str = "white") -> Path:
    Image.new("RGB", (8, 8), color=color).save(path)
    return path


def _image_with_text(path: Path) -> Path:
    image = Image.new("RGB", (8, 8), color="red")
    info = PngImagePlugin.PngInfo()
    info.add_text("prompt", "private")
    info.add_text("seed", "42")
    image.save(path, pnginfo=info)
    return path


def _playlist(path: Path, items: list[Path]) -> Path:
    path.write_text(
        json.dumps(
            {
                "Format": "NeeView.Playlist/2.0.0",
                "Items": [{"Path": str(item)} for item in items],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
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


def test_real_business_flow_uses_playlist_order_then_current_directory_state(
    tmp_path: Path,
    capsys,
):
    root = tmp_path / "publish"
    source = tmp_path / "source"
    source.mkdir()
    first = _image_with_text(source / "first.png")
    second = _image(source / "second.png", "blue")
    playlist = _playlist(tmp_path / "candidates.nvpls", [second, first])

    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    assert main(
        ["task", "create", str(root), "task-001", "--candidates", str(playlist)]
    ) == 0
    capsys.readouterr()

    all_dir = root / "tasks" / "task-001" / "selection" / "all"
    (all_dir / "0001_second.png").rename(all_dir / "0001_cover.png")
    (all_dir / "0002_first.png").unlink()

    assert main(["task", "build", str(root), "task-001"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["selection"]["all"] == 1
    output = Path(result["output_paths"]["all"])
    assert [path.name for path in output.glob("*.png")] == ["0001_cover.png"]
    assert read_png_text_chunks(output / "0001_cover.png") == {}
    assert (Path(result["build_root"]) / "selection_snapshot.json").is_file()
