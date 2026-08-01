from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from publishing_workspace.catalog import CatalogRepository
from publishing_workspace.config import init_workspace, load_workspace
from publishing_workspace.importing import ImportRunRepository
from publishing_workspace.importing.planner import ImportPlanner
from publishing_workspace.importing.service import ImportWorkflowService
from publishing_workspace.models import ImportedItem, SelectionSet
from publishing_workspace.service import PublishingService


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


def test_workflow_imports_then_reuses_same_selection(tmp_path: Path):
    root = tmp_path / "publish"
    source = tmp_path / "images"
    source.mkdir()
    Image.new("RGB", (2, 2), "white").save(source / "a.png")
    init_workspace(root)

    first = PublishingService().import_source(root, source, input_type="directory")
    second = PublishingService().import_source(root, source, input_type="directory")

    assert first.status == "completed"
    assert first.parsed_new_items == 1
    assert second.status == "completed"
    assert second.reused_path_items == 1
    assert second.parsed_new_items == 0
    assert Path(second.snapshot_path).is_file()


def test_resume_does_not_reload_input_adapter(tmp_path: Path, monkeypatch):
    root = tmp_path / "publish"
    source = tmp_path / "images"
    source.mkdir()
    image = source / "a.png"
    Image.new("RGB", (2, 2), "white").save(image)
    init_workspace(root)
    paths, config = load_workspace(root)
    workflow = ImportWorkflowService(paths, config)
    run = workflow.runs.create_run(
        source_type="directory", source_ref=str(source), mode="import", strict=False
    )
    workflow.runs.persist_selection(
        run.import_id,
        SelectionSet(
            id=run.import_id,
            source_type="directory",
            source_ref=str(source),
            items=[_item(0, str(image))],
        ),
    )
    ImportPlanner(workflow.catalog, workflow.runs, workflow.problems).plan(run.import_id)
    workflow.runs.transition(run.import_id, status="planned", pipeline_stage="execution")
    workflow.runs.transition(run.import_id, status="running", pipeline_stage="execution")
    workflow.runs.interrupt(run.import_id, reason="test interruption")

    monkeypatch.setattr(
        "publishing_workspace.importing.service.default_input_registry",
        lambda: (_ for _ in ()).throw(AssertionError("resume 不应读取 InputAdapter")),
    )
    result = workflow.resume(run.import_id)
    assert result.status == "completed"


def test_resume_takes_over_expired_running_run(tmp_path: Path):
    root = tmp_path / "publish"
    source = tmp_path / "images"
    source.mkdir()
    image = source / "a.png"
    Image.new("RGB", (2, 2), "white").save(image)
    init_workspace(root)
    paths, config = load_workspace(root)
    workflow = ImportWorkflowService(paths, config)
    run = workflow.runs.create_run(
        source_type="directory", source_ref=str(source), mode="import", strict=False
    )
    workflow.runs.persist_selection(
        run.import_id,
        SelectionSet(
            id=run.import_id,
            source_type="directory",
            source_ref=str(source),
            items=[_item(0, str(image))],
        ),
    )
    ImportPlanner(workflow.catalog, workflow.runs, workflow.problems).plan(run.import_id)
    workflow.runs.transition(run.import_id, status="planned", pipeline_stage="execution")
    workflow.runs.transition(run.import_id, status="running", pipeline_stage="execution")
    workflow.leases.acquire(run.import_id, allow_takeover=False)
    with workflow.catalog.connection() as connection:
        connection.execute(
            "UPDATE workspace_locks SET lease_expires_at=? WHERE lock_name=?",
            ("2000-01-01T00:00:00+00:00", "publishing_import"),
        )

    result = workflow.resume(run.import_id)

    assert result.status == "completed"
    assert result.parsed_new_items == 1


def test_retry_problems_resolves_original_problem_after_fix(tmp_path: Path):
    root = tmp_path / "publish"
    source = tmp_path / "images"
    source.mkdir()
    broken = source / "broken.png"
    broken.touch()
    init_workspace(root)
    service = PublishingService()

    first = service.import_source(root, source, input_type="directory")
    assert first.failed_items == 1
    assert len(service.list_problems(root, error_code="empty_file")) == 1

    Image.new("RGB", (2, 2), "white").save(broken)
    retry = service.retry_problems(root, error_code="empty_file")

    assert retry.parsed_new_items == 1
    assert service.list_problems(root, error_code="empty_file") == []
    assert len(service.list_problems(root, status="resolved", error_code="empty_file")) == 1
