from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .schema import SCHEMA_ID, SCHEMA_SQL, SCHEMA_VERSION


def migrate_catalog_v1_to_v2(catalog_path: Path, backups_dir: Path) -> Path:
    """为 v1 Catalog 创建一致性备份，然后在事务内升级到 v2。"""
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backups_dir / f"catalog-v1-{timestamp}-{uuid4().hex[:8]}.sqlite"
    with sqlite3.connect(catalog_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)

    with sqlite3.connect(catalog_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            _ensure_legacy_tables(connection)
            _prepare_legacy_import_items(connection)
            _migrate_imports(connection)
            _migrate_import_items(connection)
            _create_support_tables(connection)
            _backfill_legacy_problems(connection)
            _set_schema_v2(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
    return backup_path


def _ensure_legacy_tables(connection: sqlite3.Connection) -> None:
    """兼容只创建 schema_meta 的早期测试库或空 Catalog。"""
    if not _table_exists(connection, "imports"):
        connection.execute(
            "CREATE TABLE imports(import_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, "
            "source_ref TEXT NOT NULL, created_at TEXT NOT NULL, warnings_json TEXT NOT NULL)"
        )
    if not _table_exists(connection, "import_items"):
        connection.execute(
            "CREATE TABLE import_items(import_id TEXT NOT NULL, source_order INTEGER NOT NULL, "
            "source_path TEXT NOT NULL, resolved_path TEXT, display_name TEXT NOT NULL, "
            "asset_id TEXT, status TEXT NOT NULL, warnings_json TEXT NOT NULL, "
            "PRIMARY KEY(import_id, source_order))"
        )


def _prepare_legacy_import_items(connection: sqlite3.Connection) -> None:
    if _table_exists(connection, "import_items_v1"):
        return
    columns = _table_columns(connection, "import_items")
    if "decision" not in columns:
        connection.execute("ALTER TABLE import_items RENAME TO import_items_v1")


def _migrate_imports(connection: sqlite3.Connection) -> None:
    columns = _table_columns(connection, "imports")
    if "mode" in columns and "pipeline_stage" in columns:
        return
    has_items = _table_exists(connection, "import_items_v1")
    connection.execute("ALTER TABLE imports RENAME TO imports_v1")
    connection.execute(
        """
        CREATE TABLE imports (
            import_id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            source_fingerprint TEXT,
            mode TEXT NOT NULL,
            strict INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            pipeline_stage TEXT NOT NULL,
            total_items INTEGER NOT NULL DEFAULT 0,
            planned_items INTEGER NOT NULL DEFAULT 0,
            processed_items INTEGER NOT NULL DEFAULT 0,
            reused_path_items INTEGER NOT NULL DEFAULT 0,
            reused_content_items INTEGER NOT NULL DEFAULT 0,
            parsed_new_items INTEGER NOT NULL DEFAULT 0,
            missing_items INTEGER NOT NULL DEFAULT 0,
            failed_items INTEGER NOT NULL DEFAULT 0,
            held_problem_items INTEGER NOT NULL DEFAULT 0,
            warnings_json TEXT NOT NULL,
            error_json TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO imports(
            import_id, source_type, source_ref, source_fingerprint, mode, strict,
            status, pipeline_stage, total_items, planned_items, processed_items,
            reused_path_items, reused_content_items, parsed_new_items, missing_items,
            failed_items, held_problem_items, warnings_json, error_json, created_at,
            started_at, updated_at, completed_at
        )
            SELECT
            i.import_id, i.source_type, i.source_ref, NULL, 'legacy', 0,
            'completed', 'completed',
                {_legacy_count_sql('x.import_id=i.import_id', has_items)},
                {_legacy_count_sql('x.import_id=i.import_id', has_items)},
                {_legacy_count_sql('x.import_id=i.import_id', has_items)},
                0, 0,
                {_legacy_count_sql("x.import_id=i.import_id AND x.status='imported'", has_items)},
                {_legacy_count_sql("x.import_id=i.import_id AND x.status='missing'", has_items)},
                {_legacy_count_sql("x.import_id=i.import_id AND x.status='failed'", has_items)},
            0, i.warnings_json, NULL, i.created_at, i.created_at, i.created_at, i.created_at
        FROM imports_v1 i
        """
    )
    connection.execute("DROP TABLE imports_v1")


def _legacy_count_sql(condition: str, available: bool) -> str:
    if not available:
        return "0"
    return f"(SELECT COUNT(*) FROM import_items_v1 x WHERE {condition})"


def _migrate_import_items(connection: sqlite3.Connection) -> None:
    columns = _table_columns(connection, "import_items")
    if "decision" in columns and "observed_size" in columns:
        return
    connection.execute(
        """
        CREATE TABLE import_items (
            import_id TEXT NOT NULL REFERENCES imports(import_id) ON DELETE CASCADE,
            source_order INTEGER NOT NULL,
            source_path TEXT NOT NULL,
            resolved_path TEXT,
            display_name TEXT NOT NULL,
            observed_size INTEGER,
            observed_modified_ns INTEGER,
            decision TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            asset_id TEXT REFERENCES assets(asset_id),
            problem_id TEXT,
            warnings_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (import_id, source_order)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO import_items(
            import_id, source_order, source_path, resolved_path, display_name,
            observed_size, observed_modified_ns, decision, status, attempts, asset_id,
            problem_id, warnings_json, created_at, updated_at
        )
        SELECT
            import_id, source_order, source_path, resolved_path, display_name,
            NULL, NULL,
            CASE status WHEN 'imported' THEN 'legacy' WHEN 'missing' THEN 'missing_path'
                 ELSE 'legacy' END,
            CASE status WHEN 'imported' THEN 'legacy' WHEN 'missing' THEN 'missing'
                 ELSE 'failed' END,
            1, asset_id, NULL, warnings_json,
            (SELECT created_at FROM imports WHERE import_id=import_items_v1.import_id),
            (SELECT updated_at FROM imports WHERE import_id=import_items_v1.import_id)
        FROM import_items_v1
        """
    )
    connection.execute("DROP TABLE import_items_v1")


def _create_support_tables(connection: sqlite3.Connection) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS import_problems (
            problem_id TEXT PRIMARY KEY,
            import_id TEXT NOT NULL REFERENCES imports(import_id) ON DELETE CASCADE,
            source_order INTEGER NOT NULL,
            path_key TEXT,
            source_path TEXT NOT NULL,
            error_code TEXT NOT NULL,
            message TEXT NOT NULL,
            observed_size INTEGER,
            observed_modified_ns INTEGER,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS workspace_locks (
            lock_name TEXT PRIMARY KEY,
            owner_run_id TEXT NOT NULL,
            owner_token TEXT NOT NULL,
            lease_expires_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS classification_profiles (
            profile_hash TEXT PRIMARY KEY,
            hierarchy_json TEXT NOT NULL,
            missing_value TEXT NOT NULL,
            skip_missing INTEGER NOT NULL,
            builder_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS asset_view_memberships (
            profile_hash TEXT NOT NULL,
            asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
            view_key TEXT NOT NULL,
            view_path_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (profile_hash, asset_id, view_key)
        )
        """,
    ]
    for statement in statements:
        connection.execute(statement)


def _backfill_legacy_problems(connection: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    rows = connection.execute(
        "SELECT import_id, source_order, source_path, status FROM import_items "
        "WHERE status IN ('missing', 'failed')"
    ).fetchall()
    for row in rows:
        error_code = "missing_path" if row["status"] == "missing" else "legacy_failure"
        problem_id = f"legacy:{row['import_id']}:{row['source_order']}"
        connection.execute(
            "INSERT OR IGNORE INTO import_problems(" 
            "problem_id, import_id, source_order, path_key, source_path, error_code, "
            "message, observed_size, observed_modified_ns, status, attempts, "
            "created_at, updated_at, resolved_at) VALUES (?, ?, ?, NULL, ?, ?, ?, NULL, NULL, 'open', 1, ?, ?, NULL)",
            (
                problem_id,
                row["import_id"],
                row["source_order"],
                row["source_path"],
                error_code,
                "历史导入记录未保存具体错误信息",
                now,
                now,
            ),
        )
        connection.execute(
            "UPDATE import_items SET problem_id=? WHERE import_id=? AND source_order=?",
            (problem_id, row["import_id"], row["source_order"]),
        )


def _set_schema_v2(connection: sqlite3.Connection) -> None:
    columns = _table_columns(connection, "schema_meta")
    if "schema_id" not in columns:
        connection.execute("ALTER TABLE schema_meta ADD COLUMN schema_id TEXT")
    connection.execute("DELETE FROM schema_meta")
    connection.execute(
        "INSERT INTO schema_meta(schema_id, version) VALUES (?, ?)",
        (SCHEMA_ID, SCHEMA_VERSION),
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )
