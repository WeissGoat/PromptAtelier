from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from publishing_workspace.catalog import CatalogRepository
from publishing_workspace.importing.executor import ImportExecutor
from publishing_workspace.importing.locks import WorkspaceLeaseRepository
from publishing_workspace.importing.planner import ImportPlanner
from publishing_workspace.importing.repository import ImportRunRepository
from publishing_workspace.metadata import default_image_node_reader_registry
from publishing_workspace.models import ImportedItem, SelectionSet
from publishing_workspace.problems import ProblemRepository


class FakeClock:
    def __init__(self):
        self.value = datetime(2026, 8, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def test_active_lease_blocks_second_writer(tmp_path: Path):
    catalog = CatalogRepository(tmp_path / "catalog.sqlite")
    leases = WorkspaceLeaseRepository(catalog)
    first = leases.acquire("run-a", allow_takeover=False)
    with pytest.raises(RuntimeError, match="run-a"):
        leases.acquire("run-b", allow_takeover=False)
    leases.release(first)
    second = leases.acquire("run-b", allow_takeover=False)
    leases.release(second)


def test_expired_lease_requires_same_run_takeover(tmp_path: Path):
    clock = FakeClock()
    catalog = CatalogRepository(tmp_path / "catalog.sqlite")
    leases = WorkspaceLeaseRepository(catalog, now=clock.now)
    leases.acquire("run-a", allow_takeover=False)
    clock.advance(91)
    with pytest.raises(RuntimeError, match="需要 resume 接管"):
        leases.acquire("run-b", allow_takeover=False)
    with pytest.raises(RuntimeError, match="只能由该 Run"):
        leases.acquire("run-b", allow_takeover=True)
    lease = leases.acquire("run-a", allow_takeover=True)
    leases.release(lease)


@dataclass
class Harness:
    catalog: CatalogRepository
    runs: ImportRunRepository
    problems: ProblemRepository
    leases: WorkspaceLeaseRepository
    run_id: str

    def executor(self) -> ImportExecutor:
        return ImportExecutor(
            catalog=self.catalog,
            runs=self.runs,
            problems=self.problems,
            leases=self.leases,
            readers=default_image_node_reader_registry(),
            enrichers=[],
        )


def _planned_harness(tmp_path: Path, count: int) -> Harness:
    catalog = CatalogRepository(tmp_path / "catalog.sqlite")
    runs = ImportRunRepository(catalog)
    problems = ProblemRepository(catalog)
    leases = WorkspaceLeaseRepository(catalog)
    source = tmp_path / "images"
    items: list[ImportedItem] = []
    for index in range(count):
        path = source / f"{index:04d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1, 1), (index % 255, 0, 0)).save(path)
        items.append(
            ImportedItem(
                source_path=str(path),
                resolved_path=str(path),
                source_type="directory",
                source_ref=str(source),
                source_order=index,
                display_name=path.name,
            )
        )
    run = runs.create_run(
        source_type="directory", source_ref=str(source), mode="import", strict=False
    )
    runs.persist_selection(
        run.import_id,
        SelectionSet(
            id=run.import_id,
            source_type="directory",
            source_ref=str(source),
            items=items,
        ),
    )
    ImportPlanner(catalog, runs, problems).plan(run.import_id)
    return Harness(catalog, runs, problems, leases, run.import_id)


class InterruptAfterFirstBatch:
    def emit(self, event, *, current, total, counters, force=False):
        if event == "execution_progress" and current >= 200:
            raise KeyboardInterrupt


def test_executor_commits_completed_batch_before_interrupt(tmp_path: Path):
    harness = _planned_harness(tmp_path, 450)
    lease = harness.leases.acquire(harness.run_id, allow_takeover=False)

    with pytest.raises(KeyboardInterrupt):
        harness.executor().execute(
            harness.run_id,
            lease=lease,
            batch_size=200,
            reporter=InterruptAfterFirstBatch(),
        )
    harness.leases.release(lease)

    run = harness.runs.get_run(harness.run_id)
    assert run.counters.processed_items == 200
    assert len(harness.runs.next_items(harness.run_id, status="planned", limit=500)) == 250


def test_executor_resets_processing_and_continues_in_order(tmp_path: Path):
    harness = _planned_harness(tmp_path, 3)
    with harness.catalog.connection() as connection:
        connection.execute(
            "UPDATE import_items SET status='processing' WHERE import_id=? AND source_order=0",
            (harness.run_id,),
        )
    assert harness.runs.reset_processing_to_planned(harness.run_id) == 1
    lease = harness.leases.acquire(harness.run_id, allow_takeover=False)
    harness.executor().execute(harness.run_id, lease=lease, batch_size=2)
    harness.leases.release(lease)

    with harness.catalog.connection() as connection:
        rows = connection.execute(
            "SELECT source_order, status FROM import_items WHERE import_id=? ORDER BY source_order",
            (harness.run_id,),
        ).fetchall()
    assert [row["source_order"] for row in rows] == [0, 1, 2]
    assert all(row["status"] == "parsed_new" for row in rows)
