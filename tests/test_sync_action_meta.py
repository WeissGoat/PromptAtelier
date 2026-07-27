import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
import yaml

from tags_machine_core.nodes import NodeReader
from tools.legacy_migration.sync_action_meta import (
    LOCK_FILENAME,
    ActionMetaSyncLockedError,
    sync_action_meta,
)
from tools.legacy_migration.cli import main as legacy_migration_main


def test_preview_reports_missing_meta_without_writing(tmp_path: Path):
    action_dir = tmp_path / "standing"
    action_dir.mkdir()
    (action_dir / "tags.txt").write_text("standing, looking at viewer", encoding="utf-8")

    report = sync_action_meta(tmp_path)

    assert report["summary"]["created"] == 1
    assert report["summary"]["errors"] == 0
    assert not (action_dir / "meta.yaml").exists()


def test_write_creates_meta_without_clothing_signals_and_is_idempotent(tmp_path: Path):
    action_dir = tmp_path / "standing"
    action_dir.mkdir()
    (action_dir / "tags.txt").write_text("standing, looking at viewer", encoding="utf-8")

    first = sync_action_meta(tmp_path, write=True)
    second = sync_action_meta(tmp_path, write=True)
    node = NodeReader().read(action_dir)

    assert first["summary"]["created"] == 1
    assert second["summary"]["unchanged"] == 1
    assert node.tags["action"] == ["standing", "looking at viewer"]
    assert node.clothing == {}
    assert not list(action_dir.glob(".meta.yaml.*.tmp"))
    assert not (tmp_path / LOCK_FILENAME).exists()


def test_existing_meta_preserves_custom_fields_and_updates_clothing(tmp_path: Path):
    action_dir = tmp_path / "special_outfit"
    action_dir.mkdir()
    (action_dir / "tags.txt").write_text("standing\ntype,dress", encoding="utf-8")
    (action_dir / "classify.yaml").write_text(
        "clothing: specific_outfit\n",
        encoding="utf-8",
    )
    (action_dir / "meta.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "tags-machine.action/v1",
                "kind": "action",
                "id": "special_outfit",
                "tags": {"action": ["standing"]},
                "character_scope": "default",
                "agent": {"selected_keys": ["character", "role"]},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = sync_action_meta(tmp_path, write=True, backup=True)
    data = yaml.safe_load((action_dir / "meta.yaml").read_text(encoding="utf-8"))

    assert report["summary"]["updated"] == 1
    assert data["agent"]["selected_keys"] == ["character", "role"]
    assert data["clothing"]["state"] == "specific_outfit"
    assert data["clothing"]["action_outfit"] is True
    assert (action_dir / "meta.yaml.bak").exists()


def test_missing_tags_for_new_node_is_reported_as_error(tmp_path: Path):
    action_dir = tmp_path / "incomplete"
    action_dir.mkdir()
    (action_dir / "classify.yaml").write_text("clothing: nude\n", encoding="utf-8")

    report = sync_action_meta(tmp_path, write=True)

    assert report["summary"]["errors"] == 1
    assert report["items"][0]["status"] == "error"
    assert "missing tags.txt" in report["items"][0]["error"]
    assert not (action_dir / "meta.yaml").exists()


def test_existing_lock_blocks_write_run(tmp_path: Path):
    lock_path = tmp_path / LOCK_FILENAME
    lock_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")

    with pytest.raises(ActionMetaSyncLockedError, match="already locked"):
        sync_action_meta(tmp_path, write=True)

    assert lock_path.exists()


def test_cli_preview_writes_json_report(tmp_path: Path):
    action_dir = tmp_path / "standing"
    action_dir.mkdir()
    (action_dir / "tags.txt").write_text("standing", encoding="utf-8")
    report_path = tmp_path / "reports" / "sync.json"

    with redirect_stdout(io.StringIO()):
        exit_code = legacy_migration_main(
            [
                "sync-action-meta",
                str(tmp_path),
                "--report",
                str(report_path),
            ]
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["schema"] == "tags-machine-tools.action-meta-sync/v1"
    assert report["summary"]["created"] == 1
    assert not (action_dir / "meta.yaml").exists()


def test_cli_lock_conflict_returns_clear_error(tmp_path: Path):
    (tmp_path / LOCK_FILENAME).write_text("running", encoding="utf-8")
    stderr = io.StringIO()

    with redirect_stderr(stderr):
        exit_code = legacy_migration_main(
            ["sync-action-meta", str(tmp_path), "--write"]
        )

    assert exit_code == 2
    assert "already locked" in stderr.getvalue()
