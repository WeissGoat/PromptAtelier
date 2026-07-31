from __future__ import annotations

import json
import os
import shutil
import sqlite3
import struct
from pathlib import Path
from types import SimpleNamespace
import zlib

from PIL import Image
import pytest
import yaml

from publishing_workspace.catalog import CatalogRepository
from publishing_workspace.config import init_workspace, load_workspace
from publishing_workspace.inputs import InputContext, default_input_registry
from publishing_workspace.inputs.shortcut import resolve_shortcut
from publishing_workspace.metadata import default_image_node_reader_registry
from publishing_workspace.models import (
    AssetFingerprint,
    AssetImageInfo,
    AssetRecord,
    ImageNodeInfo,
    ImageNodeRef,
    ViewEntry,
    ViewItem,
)
from publishing_workspace.service import PublishingService
from publishing_workspace.views.builder import ClassificationViewBuilder
from publishing_workspace.views.exporters import (
    WindowsShortcutExporter,
    _create_windows_shortcut,
)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_png_text_chunks(path: Path, chunks: dict[str, str]) -> None:
    data = path.read_bytes()
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        if chunk_type == b"IEND":
            encoded = b"".join(
                _png_chunk(b"tEXt", key.encode("latin-1") + b"\x00" + value.encode("utf-8"))
                for key, value in chunks.items()
            )
            path.write_bytes(data[:offset] + encoded + data[offset:])
            return
        offset += 12 + length
    raise ValueError(f"PNG 缺少 IEND：{path}")


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


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


def _asset_with_nodes(nodes: list[ImageNodeRef]) -> AssetRecord:
    return AssetRecord(
        asset_id="sha256:test",
        path="F:/images/test.png",
        fingerprint=AssetFingerprint(size=1, modified_ns=1, sha256="test"),
        image=AssetImageInfo(width=32, height=48, format="PNG"),
        node_info=ImageNodeInfo(format="core", reader="core", nodes=nodes),
    )


def test_asset_node_projection_fills_missing_roles_and_keeps_multiple_values():
    asset = _asset_with_nodes(
        [
            ImageNodeRef(role="artist", id="artist_a"),
            ImageNodeRef(role="character", id="homura", index=0),
            ImageNodeRef(role="character", id="madoka", index=1),
            ImageNodeRef(role="action", id="standing"),
        ]
    )

    projection = asset.node_projection(
        ["artist", "character", "action_group", "action"],
        missing_value="unknown",
    )

    assert projection.values == {
        "artist": ["artist_a"],
        "character": ["homura", "madoka"],
        "action_group": ["unknown"],
        "action": ["standing"],
    }
    assert projection.missing_roles == ["action_group"]
    assert projection.has_missing is True


def test_asset_node_projection_rejects_empty_missing_value():
    asset = _asset_with_nodes([])

    with pytest.raises(ValueError, match="missing_value"):
        asset.node_projection(["artist"], missing_value=" ")


def test_classification_builds_full_unknown_path_for_asset_without_nodes():
    asset = _asset_with_nodes([])

    plan = ClassificationViewBuilder().build(
        [asset],
        hierarchy=["artist", "character", "action_group", "action"],
        missing_value="unknown",
        skip_missing=False,
    )

    assert [view.key for view in plan.views] == [
        "unknown/unknown/unknown/unknown",
    ]
    assert plan.views[0].items[0].asset_id == asset.asset_id


def test_classification_can_explicitly_skip_missing_projection():
    asset = _asset_with_nodes([ImageNodeRef(role="artist", id="artist_a")])

    plan = ClassificationViewBuilder().build(
        [asset],
        hierarchy=["artist", "character", "action"],
        missing_value="unknown",
        skip_missing=True,
    )

    assert plan.views == []


def test_classification_uses_custom_missing_value_in_each_missing_dimension():
    asset = _asset_with_nodes([ImageNodeRef(role="action", id="standing")])

    plan = ClassificationViewBuilder().build(
        [asset],
        hierarchy=["artist", "character", "action"],
        missing_value="未分类",
        skip_missing=False,
    )

    assert [view.key for view in plan.views] == [
        "未分类/未分类/standing",
    ]


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
    assert config.schema_id == "publishing-workspace.workspace/v1"


def test_workspace_load_migrates_legacy_schema(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path / "publish")
    legacy = paths.config.read_text(encoding="utf-8").replace(
        "publishing-workspace.workspace/v1",
        "tags-machine-core.publish-workspace/v1",
    )
    legacy += "\ncustom_extension:\n  enabled: true\n# 用户注释\n"
    paths.config.write_text(legacy, encoding="utf-8")

    _, config = load_workspace(tmp_path / "publish")

    migrated = yaml.safe_load(paths.config.read_text(encoding="utf-8"))
    backup = paths.config.with_name("workspace.yaml.tags-machine-core-v1.bak")
    assert config.schema_id == "publishing-workspace.workspace/v1"
    assert migrated["schema"] == "publishing-workspace.workspace/v1"
    assert migrated["custom_extension"] == {"enabled": True}
    assert backup.read_text(encoding="utf-8") == legacy


def test_catalog_migrates_legacy_schema_meta_without_losing_imports(tmp_path: Path):
    catalog = tmp_path / "catalog.sqlite"
    with sqlite3.connect(catalog) as connection:
        connection.execute("CREATE TABLE schema_meta(version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_meta(version) VALUES (1)")
        connection.execute(
            "CREATE TABLE imports("
            "import_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_ref TEXT NOT NULL, "
            "created_at TEXT NOT NULL, warnings_json TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO imports VALUES ('legacy', 'directory', 'F:/images', 'now', '[]')"
        )

    repository = CatalogRepository(catalog)

    with repository.connection() as connection:
        schema = connection.execute(
            "SELECT schema_id, version FROM schema_meta"
        ).fetchone()
        imported = connection.execute(
            "SELECT source_ref FROM imports WHERE import_id='legacy'"
        ).fetchone()
    assert dict(schema) == {
        "schema_id": "publishing-workspace.catalog/v1",
        "version": 1,
    }
    assert imported["source_ref"] == "F:/images"


def test_catalog_recovers_interrupted_legacy_schema_migration(tmp_path: Path):
    catalog = tmp_path / "catalog.sqlite"
    with sqlite3.connect(catalog) as connection:
        connection.execute(
            "CREATE TABLE schema_meta(version INTEGER NOT NULL, schema_id TEXT)"
        )
        connection.execute("INSERT INTO schema_meta(version, schema_id) VALUES (1, NULL)")

    repository = CatalogRepository(catalog)

    with repository.connection() as connection:
        row = connection.execute(
            "SELECT schema_id, version FROM schema_meta"
        ).fetchone()
    assert dict(row) == {
        "schema_id": "publishing-workspace.catalog/v1",
        "version": 1,
    }


def test_catalog_schema_migration_rolls_back_on_failure(tmp_path: Path, monkeypatch):
    catalog = tmp_path / "catalog.sqlite"
    with sqlite3.connect(catalog) as connection:
        connection.execute("CREATE TABLE schema_meta(version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_meta(version) VALUES (1)")

    def fail_after_alter(self, connection):
        connection.execute("ALTER TABLE schema_meta ADD COLUMN schema_id TEXT")
        raise RuntimeError("模拟迁移中断")

    monkeypatch.setattr(
        CatalogRepository,
        "_migrate_legacy_schema_meta",
        fail_after_alter,
    )

    with pytest.raises(RuntimeError, match="模拟迁移中断"):
        CatalogRepository(catalog)

    with sqlite3.connect(catalog) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(schema_meta)").fetchall()
        }
    assert columns == {"version"}


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


def test_shortcut_export_uses_short_temporary_path(tmp_path: Path, monkeypatch):
    temporary_root = tmp_path / "shortcuts"
    temporary_root.mkdir()
    output = tmp_path / ("分类" * 80) / "image.png.lnk"
    output.parent.mkdir()
    target = _image(tmp_path / "目标图片.png")

    def fake_run(*args, **kwargs):
        temporary_output = Path(kwargs["env"]["TMC_SHORTCUT_OUTPUT"])
        assert temporary_output.parent == temporary_root
        assert temporary_output != output
        temporary_output.write_bytes(b"shortcut")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr("publishing_workspace.views.exporters.subprocess.run", fake_run)

    _create_windows_shortcut(output, target, temporary_root)

    assert output.read_bytes() == b"shortcut"


def test_shortcut_reader_copies_long_path_before_com_read(tmp_path: Path, monkeypatch):
    shortcut = tmp_path / ("分类" * 80) / "image.png.lnk"
    shortcut.parent.mkdir()
    shortcut.write_bytes(b"shortcut")
    target = _image(tmp_path / "目标图片.png")

    def fake_run(*args, **kwargs):
        temporary_path = Path(kwargs["env"]["TMC_SHORTCUT_PATH"])
        assert temporary_path != shortcut
        assert temporary_path.read_bytes() == b"shortcut"
        return SimpleNamespace(stdout=f"{target}\n", stderr="")

    monkeypatch.setattr("publishing_workspace.inputs.shortcut.subprocess.run", fake_run)

    assert resolve_shortcut(shortcut) == target.resolve()


@pytest.mark.skipif(os.name != "nt", reason="需要 Windows WScript.Shell")
def test_windows_shortcut_long_path_round_trip(tmp_path: Path):
    target = _image(tmp_path / "原始图片.png")
    view = ViewEntry(
        path=["画风" * 35, "角色" * 35, "动作" * 35],
        items=[
            ViewItem(
                asset_id="sha256:test",
                source_path=str(target),
                display_name=target.name,
                order=0,
            )
        ],
    )
    output_root = tmp_path / "exports" / "shortcuts"

    output = WindowsShortcutExporter().export_view(view, output_root)[0]
    selection = default_input_registry().load(
        output,
        context=InputContext(strict=True),
    )

    assert len(str(output)) > 260
    assert selection.items[0].resolved_path == str(target.resolve())
    assert not list(tmp_path.rglob(".shortcut-*"))
