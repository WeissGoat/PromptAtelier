from pathlib import Path
import importlib.util
import sys

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from tags_machine_core.nodes import NodeReader

SCRIPT_PATH = PROJECT_ROOT / "scripts" / "fill_action_meta_clothing.py"
SPEC = importlib.util.spec_from_file_location("fill_action_meta_clothing", SCRIPT_PATH)
assert SPEC is not None
SCRIPT_MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SCRIPT_MODULE)
fill_action_meta_clothing = SCRIPT_MODULE.fill_action_meta_clothing


def test_preview_does_not_write_meta_yaml(tmp_path: Path):
    action_dir = tmp_path / "foot_action"
    action_dir.mkdir()
    (action_dir / "classify.yaml").write_text("clothing: specific_outfit\n", encoding="utf-8")
    (action_dir / "tags.txt").write_text("foot focus, soles\ntype,dress\n", encoding="utf-8")

    report = fill_action_meta_clothing(tmp_path, write=False)

    assert report["summary"]["created"] == 1
    assert not (action_dir / "meta.yaml").exists()
    assert report["items"][0]["clothing"]["action_outfit"] is True


def test_write_creates_action_meta_with_clothing(tmp_path: Path):
    action_dir = tmp_path / "foot_action"
    action_dir.mkdir()
    (action_dir / "classify.yaml").write_text("clothing: specific_outfit\n", encoding="utf-8")
    (action_dir / "tags.txt").write_text("foot focus, soles\ntype,dress\n", encoding="utf-8")

    report = fill_action_meta_clothing(tmp_path, write=True)
    node = NodeReader().read(action_dir)

    assert report["summary"]["created"] == 1
    assert node.kind == "action"
    assert node.tags["action"] == ["foot focus", "soles"]
    assert node.clothing["state"] == "specific_outfit"
    assert node.clothing["action_outfit"] is True
    assert node.legacy.raw_sections["prompt"] == ["foot focus, soles"]
    assert node.legacy.raw_sections["type"] == ["type,dress"]


def test_write_updates_existing_meta_only_for_clothing(tmp_path: Path):
    action_dir = tmp_path / "standing"
    action_dir.mkdir()
    (action_dir / "classify.yaml").write_text("clothing: clothed\n", encoding="utf-8")
    (action_dir / "tags.txt").write_text("standing\ntype,dress\n", encoding="utf-8")
    (action_dir / "meta.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "tags-machine.action/v1",
                "kind": "action",
                "id": "standing",
                "tags": {"action": "standing"},
                "negative_prompt": [],
                "character_scope": "default",
                "agent": {"labels": ["keep_me"]},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = fill_action_meta_clothing(tmp_path, write=True)
    data = yaml.safe_load((action_dir / "meta.yaml").read_text(encoding="utf-8"))

    assert report["summary"]["updated"] == 1
    assert data["agent"]["labels"] == ["keep_me"]
    assert data["clothing"]["state"] == "clothed"
    assert data["clothing"]["action_outfit"] is True


def test_type_no_dress_overrides_specific_outfit(tmp_path: Path):
    action_dir = tmp_path / "naked_action"
    action_dir.mkdir()
    (action_dir / "classify.yaml").write_text("clothing: specific_outfit\n", encoding="utf-8")
    (action_dir / "tags.txt").write_text("lying\ntype,no dress\n", encoding="utf-8")

    report = fill_action_meta_clothing(tmp_path, write=True)
    item = report["items"][0]

    assert item["clothing"]["action_outfit"] is False
    assert item["conflicts"] == ["specific_outfit_with_type_no_dress"]


def test_invalid_clothing_state_is_reported_without_writing_illegal_state(tmp_path: Path):
    action_dir = tmp_path / "bad_state"
    action_dir.mkdir()
    (action_dir / "classify.yaml").write_text("clothing: armor\n", encoding="utf-8")
    (action_dir / "tags.txt").write_text("standing\ntype,dress\n", encoding="utf-8")

    report = fill_action_meta_clothing(tmp_path, write=True)
    data = yaml.safe_load((action_dir / "meta.yaml").read_text(encoding="utf-8"))

    assert report["items"][0]["conflicts"] == ["invalid_clothing_state:armor"]
    assert data["clothing"]["state"] is None
    assert data["clothing"]["action_outfit"] is True
