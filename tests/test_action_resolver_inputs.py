import json
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from tags_machine_core.tools.action_resolver.readers import (
    read_image_evidence,
    read_task_evidence,
)
from tags_machine_core.tools.action_resolver.scanner import GeneratedActionInputScanner


def test_image_reader_uses_top_level_action_and_topic(tmp_path: Path) -> None:
    image_path = tmp_path / "legacy.png"
    info = PngInfo()
    info.add_text("Action", "04_post_动作A")
    info.add_text("Topic", "pn_group")
    Image.new("RGB", (4, 4)).save(image_path, pnginfo=info)

    evidence = read_image_evidence(image_path)

    assert evidence.action == "04_post_动作A"
    assert evidence.topic == "pn_group"


def test_image_reader_falls_back_to_comment_json(tmp_path: Path) -> None:
    image_path = tmp_path / "legacy.png"
    info = PngInfo()
    info.add_text("Comment", json.dumps({"action": "动作B", "topic": "st_old"}))
    Image.new("RGB", (4, 4)).save(image_path, pnginfo=info)

    evidence = read_image_evidence(image_path)

    assert evidence.action == "动作B"
    assert evidence.topic == "st_old"


def test_scanner_deduplicates_images_inside_core_task(tmp_path: Path) -> None:
    task = tmp_path / "batch" / "task"
    task.mkdir(parents=True)
    (task / "render_request.json").write_text("{}", encoding="utf-8")
    Image.new("RGB", (4, 4)).save(task / "generated.png")
    legacy = tmp_path / "batch" / "legacy.png"
    Image.new("RGB", (4, 4)).save(legacy)

    scan = GeneratedActionInputScanner().scan([tmp_path / "batch"])

    assert scan.task_dirs == [task.resolve()]
    assert scan.image_paths == [legacy.resolve()]


def test_scanner_preserves_mixed_input_order(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.png"
    Image.new("RGB", (4, 4)).save(legacy)
    task = tmp_path / "task"
    task.mkdir()
    (task / "render_request.json").write_text("{}", encoding="utf-8")

    scan = GeneratedActionInputScanner().scan([legacy, task])

    assert [(source.kind, source.path) for source in scan.sources] == [
        ("image", legacy.resolve()),
        ("task", task.resolve()),
    ]


def test_task_reader_extracts_action_node_ref(tmp_path: Path) -> None:
    task = tmp_path / "task"
    action = tmp_path / "design" / "动作改2" / "pn_group" / "00_start_动作A"
    action.mkdir(parents=True)
    task.mkdir()
    (task / "render_request.json").write_text(
        json.dumps(
            {
                "meta": {
                    "node_refs": [
                        {
                            "role": "action",
                            "id": "00_start_动作A",
                            "ref": str(action),
                            "index": 0,
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    evidence = read_task_evidence(task)

    assert len(evidence) == 1
    assert evidence[0].action == "00_start_动作A"
    assert evidence[0].topic == "pn_group"
