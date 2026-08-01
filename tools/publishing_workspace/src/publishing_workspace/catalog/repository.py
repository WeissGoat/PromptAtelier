from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from PIL import Image

from ..metadata.registry import ImageNodeReaderRegistry
from ..metadata.enrichers import ImageNodeInfoEnricher
from ..logging import get_logger
from ..models import (
    AssetFingerprint,
    AssetImageInfo,
    AssetRecord,
    ImageNodeInfo,
    ImageNodeRef,
    ImportedItem,
    SelectionSet,
    utc_now_iso,
)
from ..png_metadata import read_png_text_chunks
from .migrations import migrate_catalog_v1_to_v2
from .schema import SCHEMA_ID, SCHEMA_SQL, SCHEMA_VERSION


logger = get_logger(__name__)


class CatalogRepository:
    def __init__(self, path: str | Path, *, backups_dir: str | Path | None = None):
        self.path = Path(path)
        self.backups_dir = (
            Path(backups_dir) if backups_dir is not None else self.path.parent / "backups"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        version = self._read_version()
        if version is None:
            with self.connection() as connection:
                connection.executescript(SCHEMA_SQL)
                connection.execute(
                    "INSERT INTO schema_meta(schema_id, version) VALUES (?, ?)",
                    (SCHEMA_ID, SCHEMA_VERSION),
                )
            return
        if version == 1:
            backup = migrate_catalog_v1_to_v2(self.path, self.backups_dir)
            logger.warning("Publishing Catalog 已从 v1 升级到 v2，备份：%s", backup)
            return
        if version != SCHEMA_VERSION:
            raise RuntimeError(f"不支持的 Publishing Catalog schema version：{version}")
        with self.connection() as connection:
            connection.executescript(SCHEMA_SQL)

    def _read_version(self) -> int | None:
        if not self.path.exists():
            return None
        with sqlite3.connect(self.path) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(schema_meta)").fetchall()
            }
            if not columns:
                return None
            if "version" not in columns:
                raise RuntimeError("无法识别的 Publishing Catalog schema_meta")
            row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                return None
            return int(row[0])

    def _migrate_legacy_schema_meta(self, connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(schema_meta)").fetchall()
        }
        if "schema_id" in columns:
            rows = connection.execute(
                "SELECT schema_id, version FROM schema_meta"
            ).fetchall()
            if rows and any(row["schema_id"] is None for row in rows):
                recoverable = all(
                    row["schema_id"] is None and int(row["version"]) == SCHEMA_VERSION
                    for row in rows
                )
                if not recoverable:
                    raise RuntimeError("Publishing Catalog schema 迁移中间态无法恢复")
                connection.execute(
                    "UPDATE schema_meta SET schema_id=? WHERE schema_id IS NULL",
                    (SCHEMA_ID,),
                )
                logger.warning("Publishing Catalog schema 迁移已恢复：%s", self.path)
            return
        if columns != {"version"}:
            raise RuntimeError(f"无法识别的 Publishing Catalog schema_meta：{sorted(columns)}")
        rows = connection.execute("SELECT version FROM schema_meta").fetchall()
        if any(int(row["version"]) != SCHEMA_VERSION for row in rows):
            versions = sorted({int(row["version"]) for row in rows})
            raise RuntimeError(
                f"不支持的旧 Publishing Catalog schema version：{versions}"
            )
        connection.execute("ALTER TABLE schema_meta ADD COLUMN schema_id TEXT")
        if rows:
            connection.execute(
                "UPDATE schema_meta SET schema_id=?",
                (SCHEMA_ID,),
            )
        else:
            connection.execute(
                "INSERT INTO schema_meta(version, schema_id) VALUES (?, ?)",
                (SCHEMA_VERSION, SCHEMA_ID),
            )
        logger.warning("Publishing Catalog schema 已升级：%s", self.path)

    def import_selection(
        self,
        selection: SelectionSet,
        *,
        readers: ImageNodeReaderRegistry,
        enrichers: list[ImageNodeInfoEnricher] | None = None,
        strict: bool = False,
    ) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "imported": 0,
            "missing": 0,
            "failed": 0,
            "asset_ids": set(),
            "reader_counts": {},
            "warnings": list(selection.warnings),
            "items": [],
        }
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO imports(import_id, source_type, source_ref, source_fingerprint, mode, strict, "
                "status, pipeline_stage, total_items, warnings_json, created_at, started_at, updated_at) "
                "VALUES (?, ?, ?, NULL, 'import', ?, 'running', 'execution', ?, ?, ?, ?, ?)",
                (
                    selection.id,
                    selection.source_type,
                    selection.source_ref,
                    int(strict),
                    len(selection.items),
                    _json(selection.warnings),
                    selection.created_at,
                    selection.created_at,
                    selection.created_at,
                ),
            )
            for item in selection.items:
                self._import_item(
                    connection,
                    selection.id,
                    item,
                    readers,
                    enrichers or [],
                    strict,
                    stats,
                )
            connection.execute(
                "UPDATE imports SET status=?, pipeline_stage='completed', processed_items=?, "
                "planned_items=?, reused_path_items=0, reused_content_items=0, "
                "parsed_new_items=?, missing_items=?, failed_items=?, warnings_json=?, "
                "updated_at=?, completed_at=? WHERE import_id=?",
                (
                    "completed_with_errors" if stats["failed"] or stats["missing"] else "completed",
                    stats["imported"] + stats["missing"] + stats["failed"],
                    len(selection.items),
                    stats["imported"],
                    stats["missing"],
                    stats["failed"],
                    _json(stats["warnings"]),
                    utc_now_iso(),
                    utc_now_iso(),
                    selection.id,
                ),
            )
        return stats

    def _import_item(
        self,
        connection: sqlite3.Connection,
        import_id: str,
        item: ImportedItem,
        readers: ImageNodeReaderRegistry,
        enrichers: list[ImageNodeInfoEnricher],
        strict: bool,
        stats: dict[str, Any],
    ) -> None:
        if not item.resolved_path:
            stats["missing"] += 1
            self._insert_import_item(connection, import_id, item, status="missing", asset_id=None)
            stats["items"].append(_snapshot_item(item, status="missing", asset_id=None))
            return

        path = Path(item.resolved_path)
        try:
            asset = self._read_or_reuse_asset(connection, path, readers, enrichers)
        except Exception as exc:
            if strict:
                raise
            warning = f"图片导入失败：{path}：{exc}"
            failed_item = item.model_copy(update={"warnings": [*item.warnings, warning]})
            stats["failed"] += 1
            stats["warnings"].append(warning)
            self._insert_import_item(
                connection,
                import_id,
                failed_item,
                status="failed",
                asset_id=None,
            )
            stats["items"].append(
                _snapshot_item(failed_item, status="failed", asset_id=None)
            )
            return

        stats["imported"] += 1
        stats["asset_ids"].add(asset.asset_id)
        counts = stats["reader_counts"]
        counts[asset.node_info.reader] = counts.get(asset.node_info.reader, 0) + 1
        stats["warnings"].extend(asset.warnings)
        self._insert_import_item(
            connection,
            import_id,
            item,
            status="imported",
            asset_id=asset.asset_id,
        )
        stats["items"].append(
            _snapshot_item(item, status="imported", asset_id=asset.asset_id)
        )

    def _read_or_reuse_asset(
        self,
        connection: sqlite3.Connection,
        path: Path,
        readers: ImageNodeReaderRegistry,
        enrichers: list[ImageNodeInfoEnricher],
    ) -> AssetRecord:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
        path_key = normalize_path_key(resolved)
        cached = connection.execute(
            "SELECT asset_id FROM asset_paths WHERE path_key=? AND size=? AND modified_ns=?",
            (path_key, stat.st_size, stat.st_mtime_ns),
        ).fetchone()
        if cached is not None:
            connection.execute(
                "UPDATE asset_paths SET available=1, last_seen_at=? WHERE path_key=?",
                (utc_now_iso(), path_key),
            )
            return self._asset_from_db(connection, cached["asset_id"], preferred_path=resolved)

        digest = _sha256_file(resolved)
        asset_id = f"sha256:{digest}"
        existing = connection.execute(
            "SELECT asset_id FROM assets WHERE sha256=?", (digest,)
        ).fetchone()
        if existing is None:
            with Image.open(resolved) as image:
                width, height = image.size
                image_format = image.format or resolved.suffix.lstrip(".").upper()
                metadata = dict(image.info)
            if image_format.casefold() == "png":
                # core 的兼容文本块可能位于 IDAT 之后，Pillow 延迟加载时不会出现在 image.info。
                metadata.update(read_png_text_chunks(resolved))
            node_info = readers.read(resolved, metadata)
            for enricher in enrichers:
                node_info = enricher.enrich(resolved, node_info)
            now = utc_now_iso()
            connection.execute(
                "INSERT INTO assets(asset_id, sha256, size, width, height, image_format, "
                "metadata_format, reader, warnings_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    asset_id,
                    digest,
                    stat.st_size,
                    width,
                    height,
                    image_format,
                    node_info.format,
                    node_info.reader,
                    _json(node_info.warnings),
                    now,
                    now,
                ),
            )
            self._replace_nodes(connection, asset_id, node_info)
        else:
            asset_id = existing["asset_id"]

        connection.execute(
            "INSERT INTO asset_paths(path_key, path, asset_id, size, modified_ns, available, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?) "
            "ON CONFLICT(path_key) DO UPDATE SET path=excluded.path, asset_id=excluded.asset_id, "
            "size=excluded.size, modified_ns=excluded.modified_ns, available=1, "
            "last_seen_at=excluded.last_seen_at",
            (path_key, str(resolved), asset_id, stat.st_size, stat.st_mtime_ns, utc_now_iso()),
        )
        return self._asset_from_db(connection, asset_id, preferred_path=resolved)

    def _replace_nodes(
        self,
        connection: sqlite3.Connection,
        asset_id: str,
        node_info: ImageNodeInfo,
    ) -> None:
        connection.execute("DELETE FROM asset_nodes WHERE asset_id=?", (asset_id,))
        for node in node_info.nodes:
            connection.execute(
                "INSERT OR IGNORE INTO asset_nodes(asset_id, role, node_index, node_id, ref) "
                "VALUES (?, ?, ?, ?, ?)",
                (asset_id, node.role, node.index, node.id or "", node.ref or ""),
            )

    def lookup_path_asset(
        self,
        connection: sqlite3.Connection,
        path_key: str,
        size: int,
        modified_ns: int,
    ) -> str | None:
        row = connection.execute(
            "SELECT asset_id FROM asset_paths WHERE path_key=? AND size=? AND modified_ns=? "
            "AND available=1",
            (path_key, size, modified_ns),
        ).fetchone()
        return str(row["asset_id"]) if row is not None else None

    def _insert_import_item(
        self,
        connection: sqlite3.Connection,
        import_id: str,
        item: ImportedItem,
        *,
        status: str,
        asset_id: str | None,
    ) -> None:
        connection.execute(
            "INSERT INTO import_items(import_id, source_order, source_path, resolved_path, "
            "display_name, decision, status, attempts, asset_id, warnings_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (
                import_id,
                item.source_order,
                item.source_path,
                item.resolved_path,
                item.display_name,
                "legacy" if status == "imported" else ("missing_path" if status == "missing" else "parse"),
                status,
                asset_id,
                _json(item.warnings),
                utc_now_iso(),
                utc_now_iso(),
            ),
        )

    def assets_for_import(self, import_id: str | None = None) -> list[AssetRecord]:
        with self.connection() as connection:
            if import_id:
                rows = connection.execute(
                    "SELECT ii.asset_id, ii.resolved_path, ii.source_order, ii.display_name "
                    "FROM import_items ii WHERE ii.import_id=? AND ii.asset_id IS NOT NULL "
                    "ORDER BY ii.source_order",
                    (import_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT ii.asset_id, ii.resolved_path, ii.source_order, ii.display_name "
                    "FROM import_items ii JOIN imports i ON i.import_id=ii.import_id "
                    "WHERE ii.asset_id IS NOT NULL ORDER BY i.rowid, ii.source_order"
                ).fetchall()
            records: list[AssetRecord] = []
            seen: set[str] = set()
            for row in rows:
                if row["asset_id"] in seen:
                    continue
                seen.add(row["asset_id"])
                record = self._asset_from_db(
                    connection,
                    row["asset_id"],
                    preferred_path=Path(row["resolved_path"]),
                )
                records.append(
                    record.model_copy(
                        update={
                            "source_order": row["source_order"],
                            "display_name": row["display_name"],
                        }
                    )
                )
            return records

    def latest_import_id(self, connection: sqlite3.Connection | None = None) -> str | None:
        if connection is None:
            with self.connection() as own_connection:
                return self.latest_import_id(own_connection)
        row = connection.execute(
            "SELECT import_id FROM imports ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return row["import_id"] if row else None

    def _asset_from_db(
        self,
        connection: sqlite3.Connection,
        asset_id: str,
        *,
        preferred_path: Path,
    ) -> AssetRecord:
        asset = connection.execute(
            "SELECT * FROM assets WHERE asset_id=?", (asset_id,)
        ).fetchone()
        if asset is None:
            raise KeyError(f"Catalog 中找不到资产：{asset_id}")
        path_row = connection.execute(
            "SELECT * FROM asset_paths WHERE path_key=? AND asset_id=?",
            (normalize_path_key(preferred_path), asset_id),
        ).fetchone()
        if path_row is None:
            path_row = connection.execute(
                "SELECT * FROM asset_paths WHERE asset_id=? ORDER BY available DESC, rowid LIMIT 1",
                (asset_id,),
            ).fetchone()
        node_rows = connection.execute(
            "SELECT role, node_index, node_id, ref FROM asset_nodes "
            "WHERE asset_id=? ORDER BY role, node_index, rowid",
            (asset_id,),
        ).fetchall()
        node_info = ImageNodeInfo(
            format=asset["metadata_format"],
            reader=asset["reader"],
            nodes=[
                ImageNodeRef(
                    role=row["role"],
                    id=row["node_id"] or None,
                    ref=row["ref"] or None,
                    index=row["node_index"],
                )
                for row in node_rows
            ],
            warnings=json.loads(asset["warnings_json"]),
        )
        return AssetRecord(
            asset_id=asset_id,
            path=path_row["path"],
            fingerprint=AssetFingerprint(
                size=path_row["size"],
                modified_ns=path_row["modified_ns"],
                sha256=asset["sha256"],
            ),
            image=AssetImageInfo(
                width=asset["width"],
                height=asset["height"],
                format=asset["image_format"],
            ),
            node_info=node_info,
            display_name=Path(path_row["path"]).name,
            warnings=list(node_info.warnings),
        )

    def read_export_states(self, exporter: str) -> dict[str, dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT view_key, content_hash, outputs_json FROM export_states WHERE exporter=?",
                (exporter,),
            ).fetchall()
        return {
            row["view_key"]: {
                "content_hash": row["content_hash"],
                "outputs": json.loads(row["outputs_json"]),
            }
            for row in rows
        }

    def replace_export_states(
        self,
        exporter: str,
        states: dict[str, dict[str, Any]],
    ) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM export_states WHERE exporter=?", (exporter,))
            for view_key, state in states.items():
                connection.execute(
                    "INSERT INTO export_states(exporter, view_key, content_hash, outputs_json, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        exporter,
                        view_key,
                        state["content_hash"],
                        _json(state.get("outputs", [])),
                        utc_now_iso(),
                    ),
                )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_path_key(path: Path) -> str:
    return str(path.expanduser().resolve()).casefold()


_path_key = normalize_path_key


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _snapshot_item(item: ImportedItem, *, status: str, asset_id: str | None) -> dict[str, Any]:
    return {
        **item.model_dump(mode="json"),
        "status": status,
        "asset_id": asset_id,
    }
