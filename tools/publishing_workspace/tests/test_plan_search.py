from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from publishing_workspace.catalog.repository import CatalogRepository
from publishing_workspace.config import init_workspace
from publishing_workspace.metadata.registry import ImageNodeReaderRegistry
from publishing_workspace.models import ImageNodeInfo, ImageNodeRef, ImportedItem, SelectionSet
from publishing_workspace.plans.models import InlineContent, MonthlyPlan, ScheduleEntry
from publishing_workspace.plans.paths import PlanPaths
from publishing_workspace.plans.repository import PlanRepository
from publishing_workspace.plans.search import AssetSearchFilter, AssetSearchService, NodeSearchService


class StaticNodeReader:
    id = "static-test"
    priority = 100

    def __init__(self, action_root: Path, character: str):
        self.action_root = action_root
        self.character = character

    def supports(self, metadata):
        return True

    def read(self, image_path, metadata):
        return ImageNodeInfo(
            format="core",
            reader=self.id,
            nodes=[
                ImageNodeRef(role="artist", id="artist_a"),
                ImageNodeRef(role="character", id=self.character),
                ImageNodeRef(role="action_group", id="st_foot"),
                ImageNodeRef(role="action", id="foot_detail", ref=str(self.action_root)),
            ],
        )


def png(path: Path, color: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)
    return path


def seed_catalog(root: Path):
    paths, _, _ = init_workspace(root)
    action_root = root / "design" / "动作改2" / "st_foot" / "foot_detail"
    action_root.mkdir(parents=True)
    (action_root / "classify.yaml").write_text(
        "phase: core\ncast: solo\ndomain: body\nsubtype:\n  sex: [kiss]\nclothing: nude\nflags:\n  - foot_focus\n",
        encoding="utf-8",
    )
    first = png(root / "images" / "first.png", "red")
    second = png(root / "images" / "second.png", "blue")
    selection = SelectionSet(
        id="import-1",
        source_type="directory",
        source_ref="test-images",
        items=[
            ImportedItem(
                source_path=str(first),
                resolved_path=str(first),
                source_type="directory",
                source_ref="test-images",
                source_order=0,
                display_name=first.name,
            ),
            ImportedItem(
                source_path=str(second),
                resolved_path=str(second),
                source_type="directory",
                source_ref="test-images",
                source_order=1,
                display_name=second.name,
            ),
        ],
    )
    reader = ImageNodeReaderRegistry(
        [StaticNodeReader(action_root, "akemi_homura")]
    )
    stats = CatalogRepository(paths.catalog).import_selection(
        selection,
        readers=reader,
        enrichers=[],
    )
    assets = CatalogRepository(paths.catalog).assets_for_import("import-1")
    return paths, stats, assets


def test_search_filters_by_import_nodes_and_classify_facets(tmp_path: Path):
    seed_catalog(tmp_path)
    service = AssetSearchService()

    result = service.search(
        tmp_path,
        AssetSearchFilter(
            import_id="import-1",
            character="homura",
            facets={"clothing": {"nude"}, "subtype": {"kiss"}},
        ),
    )

    assert len(result) == 2
    assert result[0].values["character"] == ["akemi_homura"]
    assert result[0].facets["phase"] == ["core"]
    assert result[0].facets["subtype"] == ["kiss"]
    assert result[0].facets["flags"] == ["foot_focus"]


def test_search_empty_filters_return_all_assets(tmp_path: Path):
    seed_catalog(tmp_path)

    result = AssetSearchService().search(tmp_path, AssetSearchFilter())

    assert len(result) == 2
    assert {item.display_name for item in result} == {"first.png", "second.png"}


def test_search_page_returns_stable_adjacent_pages(tmp_path: Path):
    seed_catalog(tmp_path)
    service = AssetSearchService()

    first = service.search_page(
        tmp_path,
        AssetSearchFilter(import_id="import-1", offset=0, limit=1),
    )
    second = service.search_page(
        tmp_path,
        AssetSearchFilter(import_id="import-1", offset=1, limit=1),
    )

    assert first.schema_id == "publishing-workspace.asset-page/v1"
    assert [item.display_name for item in first.items] == ["first.png"]
    assert first.next_offset == 1
    assert first.has_more is True
    assert [item.display_name for item in second.items] == ["second.png"]
    assert second.next_offset is None
    assert second.has_more is False
    assert not {item.asset_id for item in first.items}.intersection(
        item.asset_id for item in second.items
    )


def test_legacy_search_ignores_offset_and_includes_image_layout(tmp_path: Path):
    seed_catalog(tmp_path)

    result = AssetSearchService().search(
        tmp_path,
        AssetSearchFilter(import_id="import-1", offset=1, limit=1),
    )

    assert [item.display_name for item in result] == ["first.png"]
    assert result[0].width == 8
    assert result[0].height == 8
    assert result[0].image_format == "PNG"


def test_search_filter_rejects_invalid_page_bounds():
    with pytest.raises(ValueError):
        AssetSearchFilter(offset=-1)
    with pytest.raises(ValueError):
        AssetSearchFilter(limit=1001)


def test_search_reports_plan_usage_by_asset_id(tmp_path: Path):
    paths, _, assets = seed_catalog(tmp_path)
    plan = MonthlyPlan(
        plan_id="2026-09",
        month="2026-09",
        entries=[
            ScheduleEntry(
                entry_id="entry-1",
                scheduled_at="2026-09-05T20:00:00+08:00",
                title="已安排散图",
                content=InlineContent(
                    sets={
                        "all": [assets[0].asset_id],
                        "post": [assets[0].asset_id],
                        "cover": [],
                    }
                ),
            )
        ],
    )
    repository = PlanRepository()
    repository.create(PlanPaths.from_workspace(paths, "2026-09"))
    repository.save(PlanPaths.from_workspace(paths, "2026-09"), plan)

    result = AssetSearchService().search(tmp_path, AssetSearchFilter())
    used = next(item for item in result if item.asset_id == assets[0].asset_id)
    unused = next(item for item in result if item.asset_id == assets[1].asset_id)

    assert "plan:2026-09/entry-1" in used.usage
    assert unused.usage == []


def test_facets_are_aggregated_from_matching_assets(tmp_path: Path):
    seed_catalog(tmp_path)

    facets = AssetSearchService().facets(tmp_path, import_id="import-1")

    assert facets["clothing"] == ["nude"]
    assert facets["domain"] == ["body"]
    assert facets["subtype"] == ["kiss"]


def test_subtype_facets_flatten_mapping_list(tmp_path: Path):
    paths, _, assets = seed_catalog(tmp_path)
    action_path = paths.root / "design" / "动作改2" / "st_foot" / "foot_detail" / "classify.yaml"
    action_path.write_text(
        "phase: core\nsubtype:\n  - foot: [sole_focus, barefoot]\n  - sex: [kiss]\n",
        encoding="utf-8",
    )

    facets = AssetSearchService().facets(tmp_path, import_id="import-1")

    assert facets["subtype"] == ["barefoot", "kiss", "sole_focus"]


def test_node_search_lists_fuzzy_candidates_with_paging(tmp_path: Path):
    seed_catalog(tmp_path)

    result = NodeSearchService().search(
        tmp_path,
        role="character",
        query="hom",
        offset=0,
        limit=20,
    )

    assert [item.name for item in result.nodes] == ["akemi_homura"]
    assert result.has_more is False
