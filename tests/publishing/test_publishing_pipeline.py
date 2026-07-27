from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

from tags_machine_core.execution import write_png_text_chunks
from tags_machine_core.publishing.catalog import CatalogRepository
from tags_machine_core.publishing.config import init_workspace, load_workspace
from tags_machine_core.publishing.inputs import InputContext, default_input_registry
from tags_machine_core.publishing.metadata import default_image_node_reader_registry
from tags_machine_core.publishing.service import PublishingService


def _image(path: Path, chunks: dict[str, str] | None = None) -> Path:
    Image.new("RGB", (32, 48), color=(80, 90, 100)).save(path)
    if chunks:
        write_png_text_chunks(path, chunks)
    return path


def _core_chunks(*, characters: list[str] | None = None) -> dict[str, str]:
    nodes = [
        {"role": "artist", "id": "artist_a", "ref": "F:/artist_a", "index": 0},
        {"role": "action_group", "id": "st_sfw", "ref": "F:/st_sfw", "index": 0},
        {"role": "action", "id": "standing", "ref": "F:/st_sfw/standing", "index": 0},
    ]
    nodes.extend(
        {
            "role": "character",
            "id": character,
            "ref": f"F:/characters/{character}",
            "index": index,
        }
        for index, character in enumerate(characters or ["homura"])
    )
    return {
        "tags_machine_core": json.dumps(
            {
                "schema": "tags-machine-core.png-info/v1",
                "nodes": nodes,
                "source_nodes": [item["ref"] for item in nodes],
            },
            ensure_ascii=False,
        )
    }


def test_workspace_init_is_idempotent(tmp_path: Path):
    paths, config, created = init_workspace(tmp_path / "publish")
    assert created is True
    assert paths.config.is_file()
    paths.config.write_text(
        paths.config.read_text(encoding="utf-8").replace("missing_value: unknown", "missing_value: 未分类"),
        encoding="utf-8",
    )

    _, second_config, created_again = init_workspace(tmp_path / "publish")

    assert created_again is False
    assert second_config.classification.missing_value == "未分类"
    assert config.schema_id == "tags-machine-core.publish-workspace/v1"


def test_neev_input_keeps_order_and_reports_missing(tmp_path: Path):
    first = _image(tmp_path / "10.png")
    second = _image(tmp_path / "2.png")
    playlist = tmp_path / "selected.nvpls"
    playlist.write_text(
        json.dumps(
            {
                "Format": "NeeView.Playlist/2.0.0",
                "Items": [
                    {"Path": str(first)},
                    {"Path": str(tmp_path / "missing.png")},
                    {"Path": str(second)},
                ],
            }
        ),
        encoding="utf-8",
    )

    selection = default_input_registry().load(
        playlist,
        context=InputContext(strict=False),
    )

    assert [item.source_order for item in selection.items] == [0, 1, 2]
    assert [item.display_name for item in selection.items] == ["10.png", "missing.png", "2.png"]
    assert selection.items[1].resolved_path is None
    assert "图片不存在" in selection.items[1].warnings[0]


def test_reader_prefers_core_and_falls_back_to_legacy(tmp_path: Path):
    registry = default_image_node_reader_registry()
    core = registry.read(tmp_path / "core.png", _core_chunks(characters=["homura", "madoka"]))
    fallback = registry.read(
        tmp_path / "legacy.png",
        {
            "tags_machine_core": "{broken",
            "artist": "legacy_artist",
            "character": '["homura", "madoka"]',
            "topic": "st_foot",
            "action": "foot_detail",
        },
    )

    assert core.reader == "core"
    assert core.values_for("character") == ["homura", "madoka"]
    assert fallback.reader == "legacy"
    assert fallback.values_for("character") == ["homura", "madoka"]
    assert "core Reader 读取失败" in fallback.warnings[0]


def test_import_enriches_action_group_from_neighbor_manifest(tmp_path: Path):
    action_root = tmp_path / "design" / "actions"
    action = action_root / "new" / "standing"
    action.mkdir(parents=True)
    (action_root / "category_view_manifest.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "source": "new/standing",
                        "dest": "st_sfw/01_standing",
                        "root": "st_sfw",
                    },
                    {
                        "source": "new/standing",
                        "dest": "st_pose/02_standing",
                        "root": "st_pose",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source"
    source.mkdir()
    chunks = _core_chunks()
    core_data = json.loads(chunks["tags_machine_core"])
    core_data["nodes"] = [
        node for node in core_data["nodes"] if node["role"] != "action_group"
    ]
    for node in core_data["nodes"]:
        if node["role"] == "action":
            node["ref"] = str(action)
            node["id"] = "standing"
    chunks["tags_machine_core"] = json.dumps(core_data)
    _image(source / "core.png", chunks)
    root = tmp_path / "publish"
    service = PublishingService()
    service.initialize(root)

    imported = service.import_source(root, source)
    plan, _ = service.classify(root, import_id=imported.import_id)

    assert [view.key for view in plan.views] == [
        "artist_a/homura/st_pose/standing",
        "artist_a/homura/st_sfw/standing",
    ]


def test_full_pipeline_deduplicates_and_exports_multi_character_views(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    first = _image(source / "first.png", _core_chunks(characters=["homura", "madoka"]))
    shutil.copy2(first, source / "duplicate.png")
    root = tmp_path / "publish"
    service = PublishingService()
    service.initialize(root)

    imported = service.import_source(root, source, input_type="directory")
    plan, first_export = service.export(root)
    _, second_export = service.export(root)

    assert imported.total_items == 2
    assert imported.unique_assets == 1
    assert imported.reader_counts == {"core": 2}
    assert [view.key for view in plan.views] == [
        "artist_a/homura/st_sfw/standing",
        "artist_a/madoka/st_sfw/standing",
    ]
    assert first_export.results[0].written == 2
    assert second_export.results[0].skipped == 2
    paths, _ = load_workspace(root)
    homura_playlist = paths.exports / "neev" / "artist_a" / "homura" / "st_sfw" / "standing.nvpls"
    data = json.loads(homura_playlist.read_text(encoding="utf-8"))
    assert data["Format"] == "NeeView.Playlist/2.0.0"
    assert data["Items"] == [{"Path": plan.views[0].items[0].source_path}]

    repository = CatalogRepository(paths.catalog)
    assert len(repository.assets_for_import(imported.import_id)) == 1


def test_catalog_export_keeps_assets_from_previous_imports(tmp_path: Path):
    first_source = tmp_path / "first"
    second_source = tmp_path / "second"
    first_source.mkdir()
    second_source.mkdir()
    _image(first_source / "homura.png", _core_chunks(characters=["homura"]))
    _image(second_source / "madoka.png", _core_chunks(characters=["madoka"]))
    root = tmp_path / "publish"
    service = PublishingService()
    service.initialize(root)
    first_import = service.import_source(root, first_source)
    service.import_source(root, second_source)

    catalog_plan, _ = service.export(root)
    scoped_plan, scoped_export = service.export(root, import_id=first_import.import_id)

    assert [view.key for view in catalog_plan.views] == [
        "artist_a/homura/st_sfw/standing",
        "artist_a/madoka/st_sfw/standing",
    ]
    assert [view.key for view in scoped_plan.views] == [
        "artist_a/homura/st_sfw/standing",
    ]
    assert Path(scoped_export.results[0].output_root).parts[-2:] == (
        "_imports",
        first_import.import_id,
    )
