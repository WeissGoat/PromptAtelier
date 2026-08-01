from __future__ import annotations

from pathlib import Path

import pytest

from publishing_workspace.catalog import CatalogRepository
from publishing_workspace.importing import ImportRunRepository
from publishing_workspace.models import ImportedItem, SelectionSet


def _item(order: int, path: str) -> ImportedItem:
    return ImportedItem(
        source_path=path,
        resolved_path=path,
        source_type="directory",
        source_ref="F:/images",
        source_order=order,
        display_name=Path(path).name,
    )


def test_import_run_persists_selection_before_planning(tmp_path: Path):
    catalog = CatalogRepository(tmp_path / "catalog.sqlite")
    runs = ImportRunRepository(catalog)
    run = runs.create_run(
        source_type="auto",
        source_ref="E:/selected.nvpls",
        mode="import",
        strict=False,
    )
    selection = SelectionSet(
        id=run.import_id,
        source_type="neev_playlist",
        source_ref="E:/selected.nvpls",
        items=[_item(0, "E:/a.png"), _item(1, "E:/b.png")],
    )

    runs.persist_selection(run.import_id, selection)

    stored = runs.get_run(run.import_id)
    items = runs.next_items(run.import_id, status="pending", limit=200)
    assert stored.status == "scanning"
    assert stored.counters.total_items == 2
    assert stored.source_type == "neev_playlist"
    assert [item.source_order for item in items] == [0, 1]
    assert all(item.decision == "pending" and item.status == "pending" for item in items)
    assert stored.source_fingerprint


def test_import_run_rejects_invalid_transition(tmp_path: Path):
    runs = ImportRunRepository(CatalogRepository(tmp_path / "catalog.sqlite"))
    run = runs.create_run(
        source_type="auto",
        source_ref="E:/selected.nvpls",
        mode="import",
        strict=False,
    )

    with pytest.raises(ValueError, match="非法 ImportRun 状态转换"):
        runs.transition(run.import_id, status="completed", pipeline_stage="completed")


def test_import_run_counters_are_recomputed_from_item_status(tmp_path: Path):
    catalog = CatalogRepository(tmp_path / "catalog.sqlite")
    runs = ImportRunRepository(catalog)
    run = runs.create_run(
        source_type="directory",
        source_ref="F:/images",
        mode="import",
        strict=False,
    )
    runs.persist_selection(
        run.import_id,
        SelectionSet(
            id=run.import_id,
            source_type="directory",
            source_ref="F:/images",
            items=[_item(0, "F:/a.png"), _item(1, "F:/b.png")],
        ),
    )
    with catalog.connection() as connection:
        runs.mark_planned(
            connection,
            runs.get_item(run.import_id, 0),
            decision="missing_path",
            size=None,
            modified_ns=None,
        )
        runs.mark_planned(
            connection,
            runs.get_item(run.import_id, 1),
            decision="parse",
            size=10,
            modified_ns=20,
        )
        runs.mark_processing(connection, run.import_id, 0)
        runs.complete_item(connection, run.import_id, 0, status="missing")
        counters = runs.recalculate_counters(connection, run.import_id)

    assert counters.total_items == 2
    assert counters.processed_items == 1
    assert counters.missing_items == 1
    assert counters.planned_items == 1
