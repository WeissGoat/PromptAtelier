from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..catalog import CatalogRepository
from ..catalog.repository import normalize_path_key
from ..models import utc_now_iso
from ..problems import ProblemCode, ProblemRepository
from .models import ImportDecision, ImportItemRecord
from .repository import ImportRunRepository


class PlannedDecision(BaseModel):
    decision: ImportDecision
    size: int | None = None
    modified_ns: int | None = None
    asset_id: str | None = None
    problem_id: str | None = None
    error_code: ProblemCode | None = None
    message: str | None = None


class ImportPlanSummary(BaseModel):
    run_id: str
    planned_items: int
    decisions: dict[ImportDecision, int] = Field(default_factory=dict)


class ImportPlanner:
    def __init__(self, catalog: CatalogRepository, runs: ImportRunRepository, problems: ProblemRepository):
        self.catalog = catalog
        self.runs = runs
        self.problems = problems

    def plan(
        self,
        import_id: str,
        *,
        retry_failed: bool = False,
        batch_size: int = 200,
        reporter=None,
    ) -> ImportPlanSummary:
        decisions: dict[ImportDecision, int] = {}
        planned = 0
        while True:
            items = self.runs.next_items(import_id, status="pending", limit=batch_size)
            if not items:
                break
            with self.catalog.connection() as connection:
                for item in items:
                    decision = self._decide(connection, item, retry_failed=retry_failed)
                    problem_id = decision.problem_id
                    if decision.error_code and decision.decision != "hold_problem":
                        problem = self.problems.record(
                            connection,
                            run_id=import_id,
                            item=item,
                            path_key=normalize_path_key(Path(item.resolved_path or item.source_path)),
                            error_code=decision.error_code,
                            message=decision.message or decision.error_code,
                            size=decision.size,
                            modified_ns=decision.modified_ns,
                        )
                        problem_id = problem.problem_id
                    self.runs.mark_planned(
                        connection,
                        item,
                        decision=decision.decision,
                        size=decision.size,
                        modified_ns=decision.modified_ns,
                        problem_id=problem_id,
                    )
                    decisions[decision.decision] = decisions.get(decision.decision, 0) + 1
                    planned += 1
                    if reporter is not None:
                        reporter.emit(
                            "planning_progress",
                            current=planned,
                            total=self.runs.get_run(import_id).counters.total_items,
                            counters=self.runs.get_run(import_id).counters,
                        )
        return ImportPlanSummary(run_id=import_id, planned_items=planned, decisions=decisions)

    def _decide(
        self,
        connection,
        item: ImportItemRecord,
        *,
        retry_failed: bool,
    ) -> PlannedDecision:
        path = Path(item.resolved_path) if item.resolved_path else Path(item.source_path)
        path_key = normalize_path_key(path)
        if not item.resolved_path or not path.is_file():
            return self._problem_decision(
                connection,
                item,
                path_key=path_key,
                size=None,
                modified_ns=None,
                code="missing_path",
                message="图片路径不存在",
                retry_failed=retry_failed,
            )

        stat = path.stat()
        if stat.st_size == 0:
            return self._problem_decision(
                connection,
                item,
                path_key=path_key,
                size=0,
                modified_ns=stat.st_mtime_ns,
                code="empty_file",
                message="图片文件大小为 0 字节",
                retry_failed=retry_failed,
            )

        cached_asset = self.catalog.lookup_path_asset(
            connection, path_key, stat.st_size, stat.st_mtime_ns
        )
        if cached_asset:
            return PlannedDecision(
                decision="reuse_path",
                size=stat.st_size,
                modified_ns=stat.st_mtime_ns,
                asset_id=cached_asset,
            )

        existing = self.problems.find_open_fingerprint(
            connection,
            path_key=path_key,
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        )
        if existing is not None and not retry_failed:
            return PlannedDecision(
                decision="hold_problem",
                size=stat.st_size,
                modified_ns=stat.st_mtime_ns,
                problem_id=existing.problem_id,
            )
        return PlannedDecision(decision="parse", size=stat.st_size, modified_ns=stat.st_mtime_ns)

    def _problem_decision(
        self,
        connection,
        item: ImportItemRecord,
        *,
        path_key: str,
        size: int | None,
        modified_ns: int | None,
        code: ProblemCode,
        message: str,
        retry_failed: bool,
    ) -> PlannedDecision:
        existing = self.problems.find_open_fingerprint(
            connection,
            path_key=path_key,
            size=size,
            modified_ns=modified_ns,
        )
        if existing is not None and not retry_failed:
            return PlannedDecision(
                decision="hold_problem",
                size=size,
                modified_ns=modified_ns,
                problem_id=existing.problem_id,
            )
        return PlannedDecision(
            decision=code if code in {"missing_path", "empty_file"} else "parse",
            size=size,
            modified_ns=modified_ns,
            error_code=code,
            message=message,
        )
