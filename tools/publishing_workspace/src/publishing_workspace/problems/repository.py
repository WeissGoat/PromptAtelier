from __future__ import annotations

import sqlite3
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from ..catalog import CatalogRepository
from ..importing.models import ImportItemRecord
from ..models import utc_now_iso


ProblemStatus = Literal["open", "resolved", "ignored"]
ProblemCode = Literal[
    "missing_path",
    "empty_file",
    "unreadable_image",
    "unsupported_format",
    "metadata_read_error",
    "shortcut_resolve_error",
    "legacy_failure",
]


class ImportProblemRecord(BaseModel):
    problem_id: str
    import_id: str
    source_order: int
    path_key: str | None = None
    source_path: str
    error_code: ProblemCode
    message: str
    observed_size: int | None = None
    observed_modified_ns: int | None = None
    status: ProblemStatus
    attempts: int = 1
    created_at: str
    updated_at: str
    resolved_at: str | None = None


class ProblemRepository:
    def __init__(self, catalog: CatalogRepository):
        self.catalog = catalog

    def find_open_fingerprint(
        self,
        connection: sqlite3.Connection,
        *,
        path_key: str,
        size: int | None,
        modified_ns: int | None,
    ) -> ImportProblemRecord | None:
        row = connection.execute(
            "SELECT * FROM import_problems WHERE status='open' AND path_key IS ? "
            "AND observed_size IS ? AND observed_modified_ns IS ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (path_key, size, modified_ns),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def record(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        item: ImportItemRecord,
        path_key: str,
        error_code: ProblemCode,
        message: str,
        size: int | None,
        modified_ns: int | None,
    ) -> ImportProblemRecord:
        now = utc_now_iso()
        existing = connection.execute(
            "SELECT problem_id FROM import_problems WHERE import_id=? AND source_order=? "
            "AND error_code=? AND status='open' LIMIT 1",
            (run_id, item.source_order, error_code),
        ).fetchone()
        if existing is None:
            problem_id = f"problem:{uuid4().hex}"
            connection.execute(
                "INSERT INTO import_problems(problem_id, import_id, source_order, path_key, "
                "source_path, error_code, message, observed_size, observed_modified_ns, "
                "status, attempts, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 1, ?, ?)",
                (
                    problem_id,
                    run_id,
                    item.source_order,
                    path_key,
                    item.source_path,
                    error_code,
                    message,
                    size,
                    modified_ns,
                    now,
                    now,
                ),
            )
        else:
            problem_id = existing["problem_id"]
            connection.execute(
                "UPDATE import_problems SET path_key=?, message=?, observed_size=?, "
                "observed_modified_ns=?, attempts=attempts+1, updated_at=? "
                "WHERE problem_id=?",
                (path_key, message, size, modified_ns, now, problem_id),
            )
        row = connection.execute(
            "SELECT * FROM import_problems WHERE problem_id=?", (problem_id,)
        ).fetchone()
        return self._from_row(row)

    def resolve_matching(
        self,
        connection: sqlite3.Connection,
        *,
        path_key: str,
        size: int | None,
        modified_ns: int | None,
    ) -> int:
        now = utc_now_iso()
        cursor = connection.execute(
            "UPDATE import_problems SET status='resolved', resolved_at=?, updated_at=? "
            "WHERE status='open' AND path_key IS ? AND observed_size IS ? "
            "AND observed_modified_ns IS ?",
            (now, now, path_key, size, modified_ns),
        )
        return cursor.rowcount

    def resolve_ids(self, connection: sqlite3.Connection, problem_ids: list[str]) -> int:
        if not problem_ids:
            return 0
        now = utc_now_iso()
        placeholders = ",".join("?" for _ in problem_ids)
        cursor = connection.execute(
            f"UPDATE import_problems SET status='resolved', resolved_at=?, updated_at=? "
            f"WHERE status='open' AND problem_id IN ({placeholders})",
            [now, now, *problem_ids],
        )
        return cursor.rowcount

    def list(
        self,
        *,
        status: ProblemStatus | None = None,
        run_id: str | None = None,
        error_code: ProblemCode | None = None,
    ) -> list[ImportProblemRecord]:
        clauses: list[str] = []
        parameters: list[str] = []
        if status:
            clauses.append("status=?")
            parameters.append(status)
        if run_id:
            clauses.append("import_id=?")
            parameters.append(run_id)
        if error_code:
            clauses.append("error_code=?")
            parameters.append(error_code)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.catalog.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM import_problems {where} ORDER BY created_at, source_order",
                parameters,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ImportProblemRecord:
        return ImportProblemRecord(
            problem_id=row["problem_id"],
            import_id=row["import_id"],
            source_order=row["source_order"],
            path_key=row["path_key"],
            source_path=row["source_path"],
            error_code=row["error_code"],
            message=row["message"],
            observed_size=row["observed_size"],
            observed_modified_ns=row["observed_modified_ns"],
            status=row["status"],
            attempts=row["attempts"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            resolved_at=row["resolved_at"],
        )
