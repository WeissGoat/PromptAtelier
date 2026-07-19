import json
from pathlib import Path

import pytest

from tags_machine_core.tools.task_tools.resolver import (
    TaskArchiveNotFoundError,
    TaskArchiveReadError,
    TaskArchiveResolver,
    _merge_resources,
)
from tags_machine_core.tools.task_tools.models import RelatedResource


def _write_task(task_dir: Path, *, action: Path, artist: Path) -> Path:
    task_dir.mkdir(parents=True)
    image = task_dir / "generated.png"
    image.write_bytes(b"png")
    (task_dir / "render_request.json").write_text(
        json.dumps(
            {
                "schema": "tags-machine-core.render-request/v1",
                "meta": {
                    "node_refs": [
                        {
                            "role": "action",
                            "id": "00_start_侧脸回眸",
                            "ref": str(action),
                            "index": 0,
                        }
                    ]
                },
                "artist_payload": {
                    "artist_ref": "114425243_Soft_Akipeco_Official",
                    "path": str(artist),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return image


def test_resolver_reads_action_and_artist_from_render_request(tmp_path: Path):
    action = tmp_path / "design" / "动作" / "00_start_侧脸回眸"
    artist = tmp_path / "design" / "画风" / "114425243_Soft_Akipeco_Official"
    action.mkdir(parents=True)
    artist.mkdir(parents=True)
    image = _write_task(tmp_path / "output" / "task", action=action, artist=artist)

    contexts = TaskArchiveResolver().resolve([image])

    assert contexts.tasks[0].task_dir == image.parent.resolve()
    assert contexts.existing_paths("action") == [action.resolve()]
    assert contexts.existing_paths("artist") == [artist.resolve()]


def test_resolver_uses_nearest_parent_archive(tmp_path: Path):
    task = tmp_path / "day" / "task"
    action = tmp_path / "action"
    artist = tmp_path / "artist"
    action.mkdir()
    artist.mkdir()
    _write_task(task, action=action, artist=artist)
    nested = task / "nested"
    nested.mkdir()
    selected = nested / "note.json"
    selected.write_text("{}", encoding="utf-8")

    contexts = TaskArchiveResolver().resolve([selected])

    assert contexts.tasks[0].task_dir == task.resolve()


def test_resolver_preserves_missing_resource_with_exists_false(tmp_path: Path):
    image = _write_task(
        tmp_path / "task",
        action=tmp_path / "missing-action",
        artist=tmp_path / "missing-artist",
    )

    contexts = TaskArchiveResolver().resolve([image])

    action = contexts.tasks[0].resources_for("action")[0]
    assert action.path == (tmp_path / "missing-action").resolve()
    assert action.exists is False


def test_resolver_does_not_scan_child_directories(tmp_path: Path):
    selected = tmp_path / "day"
    selected.mkdir()
    nested = selected / "task"
    nested.mkdir()
    (nested / "render_request.json").write_text("{}", encoding="utf-8")

    with pytest.raises(TaskArchiveNotFoundError):
        TaskArchiveResolver().resolve([selected])


def test_resolver_deduplicates_task_directories(tmp_path: Path):
    image = _write_task(tmp_path / "task", action=tmp_path / "action", artist=tmp_path / "artist")

    contexts = TaskArchiveResolver().resolve([image, image.parent / "render_request.json"])

    assert len(contexts.tasks) == 1


def test_resolver_rejects_invalid_archive_json(tmp_path: Path):
    task = tmp_path / "task"
    task.mkdir()
    archive = task / "render_request.json"
    archive.write_text("{", encoding="utf-8")

    with pytest.raises(TaskArchiveReadError):
        TaskArchiveResolver().resolve([task])


def test_resolver_rejects_non_object_archive_json(tmp_path: Path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "render_request.json").write_text("[]", encoding="utf-8")

    with pytest.raises(TaskArchiveReadError):
        TaskArchiveResolver().resolve([task])


def test_resolver_does_not_guess_artist_path_from_id(tmp_path: Path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "render_request.json").write_text(
        json.dumps({"artist_payload": {"artist_ref": "20260412"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    contexts = TaskArchiveResolver().resolve([task])

    assert contexts.tasks[0].resources_for("artist") == []


def test_resolver_merges_same_role_index_and_path_across_archives(tmp_path: Path):
    task = tmp_path / "task"
    task.mkdir()
    action = tmp_path / "action"
    action.mkdir()
    (task / "render_request.json").write_text(
        json.dumps(
            {
                "meta": {
                    "node_refs": [
                        {"role": "action", "id": "shared", "ref": str(action), "index": 0}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (task / "prompt_bundle.json").write_text(
        json.dumps(
            {
                "meta": {
                    "nodes": [
                        {"role": "action", "id": "shared", "ref": str(action), "index": 0}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    contexts = TaskArchiveResolver().resolve([task])

    resources = contexts.tasks[0].resources_for("action")
    assert len(resources) == 1
    assert resources[0].path == action.resolve()


def test_resolver_keeps_same_id_with_distinct_paths_separate(tmp_path: Path):
    task = tmp_path / "task"
    task.mkdir()
    first_action = tmp_path / "action-a"
    second_action = tmp_path / "action-b"
    first_action.mkdir()
    second_action.mkdir()
    (task / "render_request.json").write_text(
        json.dumps(
            {
                "meta": {
                    "node_refs": [
                        {
                            "role": "action",
                            "id": "shared",
                            "ref": str(first_action),
                            "index": 0,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (task / "prompt_bundle.json").write_text(
        json.dumps(
            {
                "meta": {
                    "nodes": [
                        {
                            "role": "action",
                            "id": "shared",
                            "ref": str(second_action),
                            "index": 0,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    contexts = TaskArchiveResolver().resolve([task])

    assert [resource.path for resource in contexts.tasks[0].resources_for("action")] == [
        first_action.resolve(),
        second_action.resolve(),
    ]


def test_resolver_uses_id_fallback_only_without_path_or_ref(tmp_path: Path):
    task = tmp_path / "task"
    task.mkdir()
    archive_data = {
        "meta": {
            "node_refs": [{"role": "action", "id": "shared", "index": 0}],
        }
    }
    (task / "render_request.json").write_text(json.dumps(archive_data), encoding="utf-8")
    (task / "prompt_bundle.json").write_text(
        json.dumps({"meta": {"nodes": [{"role": "action", "id": "shared", "index": 0}]} }),
        encoding="utf-8",
    )

    contexts = TaskArchiveResolver().resolve([task])

    resources = contexts.tasks[0].resources_for("action")
    assert len(resources) == 1
    assert resources[0].id == "shared"
    assert resources[0].path is None


def test_resolver_prefers_absolute_path_when_ref_only_record_matches(tmp_path: Path):
    action = tmp_path / "action"
    action.mkdir()
    ref_only = RelatedResource(role="action", id="shared", ref=str(action), index=0)
    with_absolute_path = RelatedResource(
        role="action",
        id="shared",
        path=action,
        index=0,
    )

    resources = _merge_resources([ref_only], [with_absolute_path])

    assert resources == [with_absolute_path]
    assert resources[0].path == action.resolve()
    assert resources[0].exists is True
