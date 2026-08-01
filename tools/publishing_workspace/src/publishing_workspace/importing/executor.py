from __future__ import annotations

import logging
from pathlib import Path

from PIL import UnidentifiedImageError

from ..catalog import AssetChangedAfterPlanningError, CatalogRepository
from ..logging import get_logger
from ..metadata.enrichers import ImageNodeInfoEnricher
from ..metadata.readers import ImageNodeReadError
from ..metadata.registry import ImageNodeReaderRegistry
from ..problems import ProblemCode, ProblemRepository
from .locks import WorkspaceLease, WorkspaceLeaseRepository
from .models import ImportCounters, ImportItemRecord
from .repository import ImportRunRepository


logger = get_logger(__name__)


class ImportStrictFailure(RuntimeError):
    pass


class ImportExecutionSummary:
    def __init__(self, run_id: str, processed_this_call: int, counters: ImportCounters):
        self.run_id = run_id
        self.processed_this_call = processed_this_call
        self.counters = counters


class ImportExecutor:
    def __init__(
        self,
        *,
        catalog: CatalogRepository,
        runs: ImportRunRepository,
        problems: ProblemRepository,
        leases: WorkspaceLeaseRepository,
        readers: ImageNodeReaderRegistry,
        enrichers: list[ImageNodeInfoEnricher],
    ):
        self.catalog = catalog
        self.runs = runs
        self.problems = problems
        self.leases = leases
        self.readers = readers
        self.enrichers = enrichers

    def execute(
        self,
        run_id: str,
        *,
        lease: WorkspaceLease,
        batch_size: int = 200,
        reporter=None,
    ) -> ImportExecutionSummary:
        total_processed = 0
        strict_failure: ImportStrictFailure | None = None
        if reporter is not None:
            reporter.emit(
                "execution_started",
                current=0,
                total=self.runs.get_run(run_id).counters.total_items,
                counters=self.runs.get_run(run_id).counters,
                force=True,
            )
        while True:
            batch = self.runs.next_items(run_id, status="planned", limit=batch_size)
            if not batch:
                break
            with self.catalog.connection() as connection:
                batch_strict_failure: ImportStrictFailure | None = None
                for item in batch:
                    self.runs.mark_processing(connection, run_id, item.source_order)
                    try:
                        self._execute_item(connection, item)
                    except AssetChangedAfterPlanningError:
                        self.runs.reset_item_to_pending(connection, run_id, item.source_order)
                    except Exception as exc:
                        self._record_item_error(connection, item, exc)
                        if self.runs.get_run(run_id).strict:
                            batch_strict_failure = ImportStrictFailure(str(exc))
                            break
                counters = self.runs.recalculate_counters(connection, run_id)
                lease = self.leases.refresh(connection, lease)
            total_processed += len(batch)
            if reporter is not None:
                reporter.emit(
                    "execution_progress",
                    current=counters.processed_items,
                    total=counters.total_items,
                    counters=counters,
                    force=True,
                )
            if batch_strict_failure is not None:
                strict_failure = batch_strict_failure
                break
            if self.runs.has_items(run_id, status="pending"):
                break
        if reporter is not None:
            run = self.runs.get_run(run_id)
            reporter.emit(
                "execution_completed",
                current=run.counters.processed_items,
                total=run.counters.total_items,
                counters=run.counters,
                force=True,
            )
        if strict_failure is not None:
            raise strict_failure
        run = self.runs.get_run(run_id)
        return ImportExecutionSummary(run_id, total_processed, run.counters)

    def _execute_item(self, connection, item: ImportItemRecord) -> None:
        if item.decision == "hold_problem":
            self.runs.complete_item(
                connection,
                item.import_id,
                item.source_order,
                status="held_problem",
                problem_id=item.problem_id,
            )
            return
        if item.decision == "missing_path":
            self.runs.complete_item(
                connection,
                item.import_id,
                item.source_order,
                status="missing",
                problem_id=item.problem_id,
            )
            return
        if item.decision == "empty_file":
            self.runs.complete_item(
                connection,
                item.import_id,
                item.source_order,
                status="failed",
                problem_id=item.problem_id,
            )
            return
        if item.path is None:
            raise FileNotFoundError(item.source_path)
        result = self.catalog.ingest_asset(
            connection,
            item.path,
            expected_size=item.observed_size or 0,
            expected_modified_ns=item.observed_modified_ns or 0,
            readers=self.readers,
            enrichers=self.enrichers,
        )
        self.runs.complete_item(
            connection,
            item.import_id,
            item.source_order,
            status=result.outcome,
            asset_id=result.asset.asset_id,
            warnings=result.asset.warnings,
        )
        self.problems.resolve_matching(
            connection,
            path_key=str(item.path.resolve()).casefold(),
            size=item.observed_size,
            modified_ns=item.observed_modified_ns,
        )

    def _record_item_error(self, connection, item: ImportItemRecord, exc: Exception) -> None:
        code, status = _classify_error(exc)
        path = item.path or Path(item.source_path)
        problem = self.problems.record(
            connection,
            run_id=item.import_id,
            item=item,
            path_key=str(path.expanduser().resolve()).casefold(),
            error_code=code,
            message=str(exc),
            size=item.observed_size,
            modified_ns=item.observed_modified_ns,
        )
        self.runs.complete_item(
            connection,
            item.import_id,
            item.source_order,
            status=status,
            problem_id=problem.problem_id,
            warnings=[str(exc)],
        )


def _classify_error(exc: Exception) -> tuple[ProblemCode, str]:
    if isinstance(exc, FileNotFoundError):
        return "missing_path", "missing"
    if isinstance(exc, (UnidentifiedImageError, OSError)):
        return "unreadable_image", "failed"
    if isinstance(exc, ImageNodeReadError):
        return "metadata_read_error", "failed"
    return "unreadable_image", "failed"
