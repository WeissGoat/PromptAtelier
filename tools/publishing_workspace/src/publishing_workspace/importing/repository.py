from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..catalog import CatalogRepository
from ..models import ImportedItem, SelectionSet, utc_now_iso
from .models import (
    ImportCounters,
    ImportDecision,
    ImportItemRecord,
    ImportItemStatus,
    ImportMode,
    ImportRunRecord,
    ImportRunStatus,
    ImportRunSummary,
    PipelineStage,
)


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "created": {"scanning", "failed"},
    "scanning": {"planned", "interrupted", "failed"},
    "planned": {"running", "interrupted", "failed"},
    "running": {"planned", "completed", "completed_with_errors", "interrupted", "failed"},
    "interrupted": {"scanning", "planned", "running", "failed"},
    "completed": set(),
    "completed_with_errors": set(),
    "failed": set(),
}


class ImportRunRepository:
    def __init__(self, catalog: CatalogRepository):
        self.catalog = catalog

    def create_run(
        self,
        *,
        source_type: str,
        source_ref: str,
        mode: ImportMode,
        strict: bool,
    ) -> ImportRunRecord:
        now = utc_now_iso()
        import_id = uuid4().hex
        with self.catalog.connection() as connection:
            connection.execute(
                "INSERT INTO imports(import_id, source_type, source_ref, mode, strict, status, "
                "pipeline_stage, warnings_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'created', 'input', '[]', ?, ?)",
                (import_id, source_type, source_ref, mode, int(strict), now, now),
            )
        return self.get_run(import_id)

    def get_run(self, import_id: str) -> ImportRunRecord:
        with self.catalog.connection() as connection:
            row = connection.execute(
                "SELECT * FROM imports WHERE import_id=?", (import_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"ImportRun 不存在：{import_id}")
        return self._run_from_row(row)

    def latest_run(self) -> ImportRunRecord | None:
        with self.catalog.connection() as connection:
            row = connection.execute(
                "SELECT * FROM imports ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        return self._run_from_row(row) if row is not None else None

    def persist_selection(self, import_id: str, selection: SelectionSet) -> None:
        fingerprint = _selection_fingerprint(selection)
        now = utc_now_iso()
        with self.catalog.connection() as connection:
            run = connection.execute(
                "SELECT status FROM imports WHERE import_id=?", (import_id,)
            ).fetchone()
            if run is None:
                raise KeyError(f"ImportRun 不存在：{import_id}")
            if run["status"] not in {"created", "interrupted"}:
                raise ValueError(f"不能为 {run['status']} 的 ImportRun 写入 Selection")
            connection.execute(
                "UPDATE imports SET source_type=?, source_ref=?, source_fingerprint=?, "
                "status='scanning', pipeline_stage='input', total_items=?, "
                "warnings_json=?, started_at=COALESCE(started_at, ?), updated_at=? "
                "WHERE import_id=?",
                (
                    selection.source_type,
                    selection.source_ref,
                    fingerprint,
                    len(selection.items),
                    _json(selection.warnings),
                    now,
                    now,
                    import_id,
                ),
            )
            connection.executemany(
                "INSERT INTO import_items(import_id, source_order, source_path, resolved_path, "
                "display_name, decision, status, attempts, warnings_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', 'pending', 0, ?, ?, ?)",
                [
                    (
                        import_id,
                        item.source_order,
                        item.source_path,
                        item.resolved_path,
                        item.display_name,
                        _json(item.warnings),
                        now,
                        now,
                    )
                    for item in selection.items
                ],
            )

    def next_items(
        self,
        import_id: str,
        *,
        status: ImportItemStatus,
        limit: int,
    ) -> list[ImportItemRecord]:
        with self.catalog.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM import_items WHERE import_id=? AND status=? "
                "ORDER BY source_order LIMIT ?",
                (import_id, status, limit),
            ).fetchall()
        return [self._item_from_row(row) for row in rows]

    def get_item(self, import_id: str, source_order: int) -> ImportItemRecord:
        with self.catalog.connection() as connection:
            row = connection.execute(
                "SELECT * FROM import_items WHERE import_id=? AND source_order=?",
                (import_id, source_order),
            ).fetchone()
        if row is None:
            raise KeyError(f"ImportItem 不存在：{import_id}/{source_order}")
        return self._item_from_row(row)

    def transition(
        self,
        import_id: str,
        *,
        status: ImportRunStatus,
        pipeline_stage: PipelineStage,
    ) -> ImportRunRecord:
        now = utc_now_iso()
        with self.catalog.connection() as connection:
            row = connection.execute(
                "SELECT status FROM imports WHERE import_id=?", (import_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"ImportRun 不存在：{import_id}")
            current = str(row["status"])
            if status != current and status not in ALLOWED_TRANSITIONS.get(current, set()):
                raise ValueError(f"非法 ImportRun 状态转换：{current} -> {status}")
            connection.execute(
                "UPDATE imports SET status=?, pipeline_stage=?, updated_at=?, "
                "started_at=COALESCE(started_at, ?) WHERE import_id=?",
                (status, pipeline_stage, now, now if status != "created" else None, import_id),
            )
        return self.get_run(import_id)

    def mark_planned(
        self,
        connection: sqlite3.Connection,
        item: ImportItemRecord,
        *,
        decision: ImportDecision,
        size: int | None,
        modified_ns: int | None,
        problem_id: str | None = None,
    ) -> None:
        now = utc_now_iso()
        connection.execute(
            "UPDATE import_items SET observed_size=?, observed_modified_ns=?, decision=?, "
            "status='planned', problem_id=?, updated_at=? WHERE import_id=? AND source_order=?",
            (
                size,
                modified_ns,
                decision,
                problem_id,
                now,
                item.import_id,
                item.source_order,
            ),
        )

    def mark_processing(
        self,
        connection: sqlite3.Connection,
        import_id: str,
        source_order: int,
    ) -> None:
        connection.execute(
            "UPDATE import_items SET status='processing', attempts=attempts+1, updated_at=? "
            "WHERE import_id=? AND source_order=? AND status='planned'",
            (utc_now_iso(), import_id, source_order),
        )

    def complete_item(
        self,
        connection: sqlite3.Connection,
        import_id: str,
        source_order: int,
        *,
        status: ImportItemStatus,
        asset_id: str | None = None,
        problem_id: str | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        connection.execute(
            "UPDATE import_items SET status=?, asset_id=COALESCE(?, asset_id), "
            "problem_id=COALESCE(?, problem_id), warnings_json=?, updated_at=? "
            "WHERE import_id=? AND source_order=?",
            (
                status,
                asset_id,
                problem_id,
                _json(warnings or []),
                utc_now_iso(),
                import_id,
                source_order,
            ),
        )

    def reset_item_to_pending(
        self,
        connection: sqlite3.Connection,
        import_id: str,
        source_order: int,
    ) -> None:
        connection.execute(
            "UPDATE import_items SET decision='pending', status='pending', "
            "observed_size=NULL, observed_modified_ns=NULL, updated_at=? "
            "WHERE import_id=? AND source_order=?",
            (utc_now_iso(), import_id, source_order),
        )

    def reset_processing_to_planned(self, import_id: str) -> int:
        with self.catalog.connection() as connection:
            cursor = connection.execute(
                "UPDATE import_items SET status='planned', updated_at=? "
                "WHERE import_id=? AND status='processing'",
                (utc_now_iso(), import_id),
            )
        return cursor.rowcount

    def recalculate_counters(
        self,
        connection: sqlite3.Connection,
        import_id: str,
    ) -> ImportCounters:
        counts = {
            "total_items": connection.execute(
                "SELECT COUNT(*) FROM import_items WHERE import_id=?", (import_id,)
            ).fetchone()[0],
            "planned_items": connection.execute(
                "SELECT COUNT(*) FROM import_items WHERE import_id=? AND status IN ('planned', 'processing')",
                (import_id,),
            ).fetchone()[0],
            "processed_items": connection.execute(
                "SELECT COUNT(*) FROM import_items WHERE import_id=? AND status NOT IN ('pending', 'planned', 'processing')",
                (import_id,),
            ).fetchone()[0],
        }
        for field, status in (
            ("reused_path_items", "reused_path"),
            ("reused_content_items", "reused_content"),
            ("parsed_new_items", "parsed_new"),
            ("missing_items", "missing"),
            ("failed_items", "failed"),
            ("held_problem_items", "held_problem"),
        ):
            counts[field] = connection.execute(
                "SELECT COUNT(*) FROM import_items WHERE import_id=? AND status=?",
                (import_id, status),
            ).fetchone()[0]
        counters = ImportCounters(**counts)
        connection.execute(
            "UPDATE imports SET total_items=?, planned_items=?, processed_items=?, "
            "reused_path_items=?, reused_content_items=?, parsed_new_items=?, "
            "missing_items=?, failed_items=?, held_problem_items=?, updated_at=? "
            "WHERE import_id=?",
            (
                counters.total_items,
                counters.planned_items,
                counters.processed_items,
                counters.reused_path_items,
                counters.reused_content_items,
                counters.parsed_new_items,
                counters.missing_items,
                counters.failed_items,
                counters.held_problem_items,
                utc_now_iso(),
                import_id,
            ),
        )
        return counters

    def has_items(self, import_id: str, *, status: ImportItemStatus) -> bool:
        with self.catalog.connection() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM import_items WHERE import_id=? AND status=? LIMIT 1",
                    (import_id, status),
                ).fetchone()
                is not None
            )

    def has_unfinished_items(self, import_id: str) -> bool:
        with self.catalog.connection() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM import_items WHERE import_id=? "
                    "AND status IN ('pending', 'planned', 'processing') LIMIT 1",
                    (import_id,),
                ).fetchone()
                is not None
            )

    def finalize(self, import_id: str) -> ImportRunSummary:
        with self.catalog.connection() as connection:
            counters = self.recalculate_counters(connection, import_id)
            open_problems = connection.execute(
                "SELECT COUNT(*) FROM import_problems WHERE import_id=? AND status='open'",
                (import_id,),
            ).fetchone()[0]
            status: ImportRunStatus = (
                "completed_with_errors"
                if open_problems or counters.missing_items or counters.failed_items or counters.held_problem_items
                else "completed"
            )
            now = utc_now_iso()
            connection.execute(
                "UPDATE imports SET status=?, pipeline_stage='completed', completed_at=?, updated_at=? "
                "WHERE import_id=?",
                (status, now, now, import_id),
            )
        return self.summary(import_id)

    def interrupt(self, import_id: str, *, reason: str) -> ImportRunRecord:
        now = utc_now_iso()
        with self.catalog.connection() as connection:
            connection.execute(
                "UPDATE imports SET status='interrupted', error_json=?, updated_at=? WHERE import_id=?",
                (_json({"reason": reason}), now, import_id),
            )
        return self.get_run(import_id)

    def fail(self, import_id: str, exc: BaseException) -> ImportRunRecord:
        now = utc_now_iso()
        with self.catalog.connection() as connection:
            connection.execute(
                "UPDATE imports SET status='failed', error_json=?, updated_at=? WHERE import_id=?",
                (_json({"type": type(exc).__name__, "message": str(exc)}), now, import_id),
            )
        return self.get_run(import_id)

    def summary(self, import_id: str) -> ImportRunSummary:
        run = self.get_run(import_id)
        with self.catalog.connection() as connection:
            unique_assets = connection.execute(
                "SELECT COUNT(DISTINCT asset_id) FROM import_items "
                "WHERE import_id=? AND asset_id IS NOT NULL",
                (import_id,),
            ).fetchone()[0]
            open_problems = connection.execute(
                "SELECT COUNT(*) FROM import_problems WHERE import_id=? AND status='open'",
                (import_id,),
            ).fetchone()[0]
            reader_rows = connection.execute(
                "SELECT a.reader, COUNT(*) AS count "
                "FROM import_items ii JOIN assets a ON a.asset_id=ii.asset_id "
                "WHERE ii.import_id=? GROUP BY a.reader",
                (import_id,),
            ).fetchall()
        return ImportRunSummary(
            run_id=run.import_id,
            status=run.status,
            pipeline_stage=run.pipeline_stage,
            source_type=run.source_type,
            source_ref=run.source_ref,
            **run.counters.model_dump(),
            unique_assets=unique_assets,
            open_problems=open_problems,
            reader_counts={row["reader"]: row["count"] for row in reader_rows},
            warnings=run.warnings,
        )

    def items_for_snapshot(self, import_id: str) -> list[dict[str, Any]]:
        with self.catalog.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM import_items WHERE import_id=? ORDER BY source_order",
                (import_id,),
            ).fetchall()
        return [dict(row) | {"warnings": _loads(row["warnings_json"])} for row in rows]

    def problems_for_snapshot(self, import_id: str) -> list[dict[str, Any]]:
        with self.catalog.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM import_problems WHERE import_id=? ORDER BY source_order",
                (import_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _run_from_row(self, row: sqlite3.Row) -> ImportRunRecord:
        return ImportRunRecord(
            import_id=row["import_id"],
            source_type=row["source_type"],
            source_ref=row["source_ref"],
            source_fingerprint=row["source_fingerprint"],
            mode=row["mode"],
            strict=bool(row["strict"]),
            status=row["status"],
            pipeline_stage=row["pipeline_stage"],
            counters=ImportCounters(
                total_items=row["total_items"],
                planned_items=row["planned_items"],
                processed_items=row["processed_items"],
                reused_path_items=row["reused_path_items"],
                reused_content_items=row["reused_content_items"],
                parsed_new_items=row["parsed_new_items"],
                missing_items=row["missing_items"],
                failed_items=row["failed_items"],
                held_problem_items=row["held_problem_items"],
            ),
            warnings=_loads(row["warnings_json"]),
            error=_loads(row["error_json"]) if row["error_json"] else None,
            created_at=row["created_at"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> ImportItemRecord:
        return ImportItemRecord(
            import_id=row["import_id"],
            source_order=row["source_order"],
            source_path=row["source_path"],
            resolved_path=row["resolved_path"],
            display_name=row["display_name"],
            observed_size=row["observed_size"],
            observed_modified_ns=row["observed_modified_ns"],
            decision=row["decision"],
            status=row["status"],
            attempts=row["attempts"],
            asset_id=row["asset_id"],
            problem_id=row["problem_id"],
            warnings=_loads(row["warnings_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _selection_fingerprint(selection: SelectionSet) -> str:
    payload = {
        "source_type": selection.source_type,
        "source_ref": selection.source_ref,
        "items": [
            [item.source_order, item.source_path, item.resolved_path, item.display_name]
            for item in selection.items
        ],
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str) -> Any:
    return json.loads(value) if value else []
