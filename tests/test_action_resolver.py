import json
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from tags_machine_core.tools.action_resolver import resolve_generated_actions


def _write_design(tmp_path: Path) -> tuple[Path, Path, Path]:
    design = tmp_path / "design"
    action_root = design / "动作改2"
    source = action_root / "new" / "动作A"
    category = action_root / "pn_group" / "04_post_动作A"
    source.mkdir(parents=True)
    category.mkdir(parents=True)
    (action_root / "category_view_manifest.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "name": "动作A",
                        "view_name": "04_post_动作A",
                        "root": "pn_group",
                        "source": "new/动作A",
                        "dest": "pn_group/04_post_动作A",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return design, source, category


def test_old_png_topic_action_maps_to_new_source(tmp_path: Path) -> None:
    design, source, _ = _write_design(tmp_path)
    image_path = tmp_path / "legacy.png"
    info = PngInfo()
    info.add_text("action", "04_post_动作A")
    info.add_text("topic", "pn_group")
    Image.new("RGB", (4, 4)).save(image_path, pnginfo=info)

    results = resolve_generated_actions([image_path], design_root=design)

    assert results[0].status == "resolved_new"
    assert results[0].absolute_path == source.resolve()
    assert results[0].relative_path == "动作改2/new/动作A"


def test_new_task_category_ref_maps_to_new_source(tmp_path: Path) -> None:
    design, source, category = _write_design(tmp_path)
    task = tmp_path / "task"
    task.mkdir()
    (task / "render_request.json").write_text(
        json.dumps(
            {
                "meta": {
                    "node_refs": [
                        {
                            "role": "action",
                            "id": "04_post_动作A",
                            "ref": str(category),
                            "index": 0,
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    results = resolve_generated_actions([task], design_root=design)

    assert results[0].status == "resolved_new"
    assert results[0].absolute_path == source.resolve()


def test_category_directory_is_returned_as_fallback(tmp_path: Path) -> None:
    design = tmp_path / "design"
    category = design / "动作改2" / "st_old" / "2_20240720_1721464255"
    (design / "动作改2" / "new").mkdir(parents=True)
    category.mkdir(parents=True)
    image_path = tmp_path / "legacy.png"
    info = PngInfo()
    info.add_text("action", "20240720_1721464255")
    info.add_text("topic", "st_old")
    Image.new("RGB", (4, 4)).save(image_path, pnginfo=info)

    results = resolve_generated_actions([image_path], design_root=design)

    assert results[0].status == "category_fallback"
    assert results[0].absolute_path == category.resolve()


def test_relative_new_ref_is_returned_directly(tmp_path: Path) -> None:
    design = tmp_path / "design"
    source = design / "动作改2" / "new" / "动作A"
    source.mkdir(parents=True)
    task = tmp_path / "task"
    task.mkdir()
    (task / "render_request.json").write_text(
        json.dumps(
            {
                "meta": {
                    "node_refs": [
                        {
                            "role": "action",
                            "id": "动作A",
                            "ref": "new/动作A",
                            "index": 0,
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    results = resolve_generated_actions([task], design_root=design)

    assert results[0].status == "resolved_new"
    assert results[0].absolute_path == source.resolve()
