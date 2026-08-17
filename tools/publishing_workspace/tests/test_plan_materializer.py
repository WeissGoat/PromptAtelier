from __future__ import annotations

from pathlib import Path

from PIL import Image

from publishing_workspace.config import init_workspace
from publishing_workspace.models import (
    AssetFingerprint,
    AssetImageInfo,
    AssetRecord,
    ImageNodeInfo,
)
from publishing_workspace.packages.builder import PackageBuilder
from publishing_workspace.plans.materializer import InlineTaskMaterializer
from publishing_workspace.plans.models import InlineContent, ScheduleEntry


def image(path: Path, color: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)
    return path


def asset(asset_id: str, path: Path) -> AssetRecord:
    stat = path.stat()
    return AssetRecord(
        asset_id=asset_id,
        path=str(path),
        fingerprint=AssetFingerprint(
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
            sha256=asset_id.removeprefix("sha256:"),
        ),
        image=AssetImageInfo(width=8, height=8, format="PNG"),
        node_info=ImageNodeInfo(format="unknown", reader="test"),
        display_name=path.name,
    )


class FakeCatalog:
    def __init__(self, assets: list[AssetRecord]):
        self.assets = assets

    def assets_for_import(self, import_id=None):
        return list(self.assets)


def entry(assets: list[AssetRecord]) -> ScheduleEntry:
    return ScheduleEntry(
        entry_id="entry-1",
        scheduled_at="2026-09-05T20:00:00+08:00",
        title="散图测试",
        content=InlineContent(
            sets={
                "all": [assets[1].asset_id, assets[0].asset_id],
                "post": [assets[0].asset_id],
                "cover": [],
            }
        ),
    )


def test_inline_materializer_preserves_selection_order(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    first = image(tmp_path / "source" / "a.png", "red")
    second = image(tmp_path / "source" / "b.png", "blue")
    assets = [
        asset("sha256:" + "a" * 64, first),
        asset("sha256:" + "b" * 64, second),
    ]

    materialized = InlineTaskMaterializer().materialize(
        tmp_path,
        plan_id="2026-09",
        entry=entry(assets),
        catalog=FakeCatalog(assets),
        execution_id="execution-1",
    )

    assert [path.name for path in (materialized.task_paths.selection_dirs["all"]).iterdir()] == [
        "0001_b.png",
        "0002_a.png",
    ]
    assert [path.name for path in (materialized.task_paths.selection_dirs["post"]).iterdir()] == [
        "0001_a.png"
    ]
    assert materialized.task_paths.task_root.is_dir()


def test_materialized_task_builds_and_cleanup_keeps_formal_build(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    first = image(tmp_path / "source" / "a.png", "red")
    second = image(tmp_path / "source" / "b.png", "blue")
    assets = [
        asset("sha256:" + "a" * 64, first),
        asset("sha256:" + "b" * 64, second),
    ]
    materialized = InlineTaskMaterializer().materialize(
        tmp_path,
        plan_id="2026-09",
        entry=entry(assets),
        catalog=FakeCatalog(assets),
        execution_id="execution-1",
    )

    result = PackageBuilder().build_paths(
        materialized.task_paths,
        output_root=materialized.formal_builds_root,
    )
    materialized.cleanup()

    assert not materialized.temporary_root.exists()
    assert result.build_root.is_dir()
    assert len(list((result.output_paths["all"]).glob("*.png"))) == 2
    assert len(list((result.output_paths["post"]).glob("*.png"))) == 1
