from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from publishing_workspace.catalog import CatalogRepository


def _legacy_catalog(tmp_path: Path) -> Path:
    catalog = tmp_path / "workspace" / "catalog.sqlite"
    catalog.parent.mkdir(parents=True)
    with sqlite3.connect(catalog) as connection:
        connection.execute("CREATE TABLE schema_meta(version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_meta(version) VALUES (1)")
        connection.execute(
            "CREATE TABLE imports(import_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, "
            "source_ref TEXT NOT NULL, created_at TEXT NOT NULL, warnings_json TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE import_items(import_id TEXT NOT NULL, source_order INTEGER NOT NULL, "
            "source_path TEXT NOT NULL, resolved_path TEXT, display_name TEXT NOT NULL, "
            "asset_id TEXT, status TEXT NOT NULL, warnings_json TEXT NOT NULL, "
            "PRIMARY KEY(import_id, source_order))"
        )
        connection.execute(
            "INSERT INTO imports VALUES ('legacy', 'directory', 'F:/images', 'now', '[]')"
        )
        connection.execute(
            "INSERT INTO import_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy", 0, "F:/images/a.png", "F:/images/a.png", "a.png", None, "missing", "[]"),
        )
    return catalog


def test_migration_creates_backup_and_preserves_legacy_problem(tmp_path: Path):
    catalog = _legacy_catalog(tmp_path)

    CatalogRepository(catalog)

    backups = list((catalog.parent / "backups").glob("catalog-v1-*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == 1
    with sqlite3.connect(catalog) as connection:
        item = connection.execute(
            "SELECT decision, status, problem_id FROM import_items WHERE import_id='legacy'"
        ).fetchone()
        problem = connection.execute(
            "SELECT error_code, status FROM import_problems WHERE import_id='legacy'"
        ).fetchone()
    assert tuple(item) == ("missing_path", "missing", "legacy:legacy:0")
    assert tuple(problem) == ("missing_path", "open")


def test_failed_migration_keeps_original_database(tmp_path: Path, monkeypatch):
    catalog = _legacy_catalog(tmp_path)
    monkeypatch.setattr(
        "publishing_workspace.catalog.migrations._migrate_import_items",
        lambda connection: (_ for _ in ()).throw(RuntimeError("模拟迁移失败")),
    )

    with pytest.raises(RuntimeError, match="模拟迁移失败"):
        CatalogRepository(catalog)

    with sqlite3.connect(catalog) as connection:
        assert connection.execute("SELECT version FROM schema_meta").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM import_items").fetchone()[0] == 1
    assert len(list((catalog.parent / "backups").glob("catalog-v1-*.sqlite"))) == 1
