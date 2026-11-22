"""SQLite 持久化索引：支撑出图历史跨批次按节点、关键字、后端秒级筛选。"""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SCHEMA_VERSION = 2


def normalize_node_ref(value: str | None) -> str:
    return (value or "").strip().replace("\\", "/").rstrip("/").lower()


def _decode_png_bytes(value: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def read_png_text_chunks_fast(path: Path) -> dict[str, str]:
    """只读 PNG 文本块（跳过 IDAT 像素数据），比整文件读取快一个数量级。"""
    chunks: dict[str, str] = {}
    with path.open("rb") as handle:
        if handle.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
            return chunks
        while True:
            header = handle.read(8)
            if len(header) < 8:
                break
            length, chunk_type = struct.unpack(">I4s", header)
            if chunk_type in (b"tEXt", b"zTXt", b"iTXt"):
                data = handle.read(length)
                handle.seek(4, os.SEEK_CUR)
                if len(data) < length:
                    break
                decoded = _decode_text_chunk(chunk_type, data)
                if decoded is not None:
                    key, value = decoded
                    chunks[key] = value
            elif chunk_type == b"IEND":
                break
            else:
                handle.seek(length + 4, os.SEEK_CUR)
    return chunks


def _decode_text_chunk(chunk_type: bytes, data: bytes) -> tuple[str, str] | None:
    if chunk_type == b"tEXt":
        sep = data.find(b"\x00")
        if sep < 0:
            return None
        return _decode_png_bytes(data[:sep]), _decode_png_bytes(data[sep + 1 :])
    if chunk_type == b"zTXt":
        sep = data.find(b"\x00")
        if sep < 0 or sep + 2 > len(data):
            return None
        key = _decode_png_bytes(data[:sep])
        try:
            text = _decode_png_bytes(zlib.decompress(data[sep + 2 :]))
        except zlib.error:
            return None
        return key, text
    if chunk_type == b"iTXt":
        parts = data.split(b"\x00", 1)
        if len(parts) < 2 or len(parts[1]) < 2:
            return None
        key = _decode_png_bytes(parts[0])
        rest = parts[1]
        compression_flag = rest[0]
        # compression_method = rest[1]
        after_flags = rest[2:]
        lang_sep = after_flags.find(b"\x00")
        if lang_sep < 0:
            return None
        trans_rest = after_flags[lang_sep + 1 :]
        trans_sep = trans_rest.find(b"\x00")
        if trans_sep < 0:
            return None
        text_bytes = trans_rest[trans_sep + 1 :]
        if compression_flag:
            try:
                text_bytes = zlib.decompress(text_bytes)
            except zlib.error:
                return None
        return key, _decode_png_bytes(text_bytes)
    return None


@dataclass(frozen=True)
class IndexedImageEntry:
    path: Path
    run_id: str
    run_name: str
    run_kind: str
    group_name: str
    created_at: float
    mtime_ns: int
    size_bytes: int


@dataclass(frozen=True)
class NodeFilterSpec:
    role: str = ""
    name: str = ""
    ref: str = ""


class HistoryIndex:
    """用 SQLite 缓存每张历史图的摘要与节点关系，支持增量更新与后台建索引。"""

    def __init__(self, db_path: Path | None = None, *, sync_inline_limit: int = 200):
        self._db_path = db_path
        self._sync_inline_limit = sync_inline_limit
        self._lock = threading.RLock()
        self._bg_lock = threading.Lock()
        self._bg_thread: threading.Thread | None = None
        self._indexing_running = False
        self._indexing_done = 0
        self._indexing_total = 0

        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            target = str(db_path)
        else:
            target = ":memory:"

        self._conn = sqlite3.connect(target, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS images (
                path TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                run_name TEXT NOT NULL,
                run_kind TEXT NOT NULL,
                filename TEXT NOT NULL,
                group_name TEXT NOT NULL,
                created_at REAL NOT NULL,
                mtime_ns INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                backend TEXT,
                seed TEXT,
                width INTEGER,
                height INTEGER,
                timing_json TEXT,
                nodes_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS image_nodes (
                path TEXT NOT NULL,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                name_lower TEXT NOT NULL,
                ref TEXT,
                ref_norm TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_images_run ON images(run_id);
            CREATE INDEX IF NOT EXISTS idx_images_created ON images(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_images_kind ON images(run_kind);
            CREATE INDEX IF NOT EXISTS idx_image_nodes_path ON image_nodes(path);
            CREATE INDEX IF NOT EXISTS idx_image_nodes_role_name ON image_nodes(role, name_lower);
            CREATE INDEX IF NOT EXISTS idx_image_nodes_role_ref ON image_nodes(role, ref_norm);
            CREATE INDEX IF NOT EXISTS idx_image_nodes_name ON image_nodes(name_lower);
            """
        )
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None or row["value"] != str(_SCHEMA_VERSION):
            self._conn.execute("DELETE FROM image_nodes")
            self._conn.execute("DELETE FROM images")
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )
            self._conn.commit()

    def indexing_status(self) -> dict[str, Any]:
        with self._bg_lock:
            return {
                "running": self._indexing_running,
                "indexed": self._indexing_done,
                "total": self._indexing_total,
            }

    def has_records(self) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM images LIMIT 1").fetchone()
            return row is not None

    def sync(
        self,
        entries: list[IndexedImageEntry],
        summarize: Callable[[Path], dict[str, Any]],
        *,
        allow_background: bool = True,
    ) -> dict[str, Any]:
        """将当前目录扫描结果同步到 SQLite；增量文件少时同步完成，多时转后台。"""
        by_path = {str(entry.path): entry for entry in entries}
        with self._lock:
            existing_rows = self._conn.execute(
                "SELECT path, mtime_ns, size_bytes, run_id, run_name, run_kind, group_name FROM images"
            ).fetchall()
            existing = {row["path"]: row for row in existing_rows}

            removed = [path for path in existing if path not in by_path]
            if removed:
                self._delete_paths(removed)

            meta_updates: list[tuple[str, str, str, str, str]] = []
            pending: list[IndexedImageEntry] = []
            for path_str, entry in by_path.items():
                row = existing.get(path_str)
                if row is None or row["mtime_ns"] != entry.mtime_ns or row["size_bytes"] != entry.size_bytes:
                    pending.append(entry)
                elif (
                    row["run_id"] != entry.run_id
                    or row["run_name"] != entry.run_name
                    or row["run_kind"] != entry.run_kind
                    or row["group_name"] != entry.group_name
                ):
                    meta_updates.append((entry.run_id, entry.run_name, entry.run_kind, entry.group_name, path_str))

            if meta_updates:
                self._conn.executemany(
                    "UPDATE images SET run_id=?, run_name=?, run_kind=?, group_name=? WHERE path=?",
                    meta_updates,
                )
            if removed or meta_updates:
                self._conn.commit()

        total_count = len(entries)
        already_indexed = total_count - len(pending)

        if not pending:
            with self._bg_lock:
                if not self._indexing_running:
                    self._indexing_done = total_count
                    self._indexing_total = total_count
            return self.indexing_status()

        # 最新的图片优先建索引，用户刚出过的图立即可筛。
        pending.sort(key=lambda item: item.created_at, reverse=True)

        if not allow_background or len(pending) <= self._sync_inline_limit:
            self._index_batch(pending, summarize)
            with self._bg_lock:
                self._indexing_running = False
                self._indexing_done = total_count
                self._indexing_total = total_count
            return self.indexing_status()

        with self._bg_lock:
            if self._indexing_running and self._bg_thread and self._bg_thread.is_alive():
                return {
                    "running": True,
                    "indexed": self._indexing_done,
                    "total": self._indexing_total,
                }
            self._indexing_running = True
            self._indexing_done = already_indexed
            self._indexing_total = total_count
            thread = threading.Thread(
                target=self._background_index,
                args=(pending, summarize, already_indexed, total_count),
                name="history-index-worker",
                daemon=True,
            )
            self._bg_thread = thread
            thread.start()
        return self.indexing_status()

    def _background_index(
        self,
        pending: list[IndexedImageEntry],
        summarize: Callable[[Path], dict[str, Any]],
        initial_done: int,
        total_count: int,
    ) -> None:
        done = initial_done
        chunk_size = 200
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                for start in range(0, len(pending), chunk_size):
                    chunk = pending[start : start + chunk_size]
                    self._index_batch(chunk, summarize, pool=pool)
                    done += len(chunk)
                    with self._bg_lock:
                        self._indexing_done = min(done, total_count)
        finally:
            with self._bg_lock:
                self._indexing_running = False
                self._indexing_done = total_count
                self._indexing_total = total_count

    def _index_batch(
        self,
        entries: list[IndexedImageEntry],
        summarize: Callable[[Path], dict[str, Any]],
        *,
        pool: ThreadPoolExecutor | None = None,
    ) -> None:
        # 文件 I/O 放在锁外并并发读取，避免长时间阻塞前端查询。
        if pool is not None and len(entries) > 1:
            summaries = list(pool.map(lambda entry: summarize(entry.path), entries))
            prepared = list(zip(entries, summaries))
        else:
            prepared = [(entry, summarize(entry.path)) for entry in entries]
        with self._lock:
            for entry, summary in prepared:
                path_str = str(entry.path)
                nodes = summary.get("nodes") or []
                seed_val = summary.get("seed")
                timing = summary.get("timing")
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO images (
                        path, run_id, run_name, run_kind, filename, group_name,
                        created_at, mtime_ns, size_bytes,
                        backend, seed, width, height, timing_json, nodes_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        path_str,
                        entry.run_id,
                        entry.run_name,
                        entry.run_kind,
                        entry.path.name,
                        entry.group_name,
                        entry.created_at,
                        entry.mtime_ns,
                        entry.size_bytes,
                        summary.get("backend"),
                        str(seed_val) if seed_val is not None else None,
                        summary.get("width"),
                        summary.get("height"),
                        json.dumps(timing, ensure_ascii=False) if timing is not None else None,
                        json.dumps(nodes, ensure_ascii=False),
                    ),
                )
                self._conn.execute("DELETE FROM image_nodes WHERE path = ?", (path_str,))
                node_rows: list[tuple[str, str, str, str, str | None, str | None]] = []
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    role = str(node.get("role") or "").strip().lower()
                    name = str(node.get("name") or "").strip()
                    ref = str(node.get("ref") or "").strip() or None
                    if not name and not ref:
                        continue
                    node_rows.append(
                        (
                            path_str,
                            role,
                            name,
                            name.lower(),
                            ref,
                            normalize_node_ref(ref) if ref else None,
                        )
                    )
                if node_rows:
                    self._conn.executemany(
                        "INSERT INTO image_nodes(path, role, name, name_lower, ref, ref_norm) VALUES (?, ?, ?, ?, ?, ?)",
                        node_rows,
                    )
            self._conn.commit()

    def _delete_paths(self, paths: list[str]) -> None:
        chunk_size = 400
        for start in range(0, len(paths), chunk_size):
            chunk = paths[start : start + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            self._conn.execute(f"DELETE FROM image_nodes WHERE path IN ({placeholders})", chunk)
            self._conn.execute(f"DELETE FROM images WHERE path IN ({placeholders})", chunk)

    def search(
        self,
        *,
        node_filters: list[NodeFilterSpec] | None = None,
        q: str = "",
        backend: str = "",
        kind: str = "",
        run_id: str = "",
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        base_clauses: list[str] = []
        base_params: list[Any] = []

        for nf in node_filters or []:
            sub_clauses: list[str] = ["n.path = i.path"]
            sub_params: list[Any] = []
            role = nf.role.strip().lower()
            name = nf.name.strip().lower()
            ref_norm = normalize_node_ref(nf.ref)
            if role:
                sub_clauses.append("n.role = ?")
                sub_params.append(role)
            if ref_norm and name:
                sub_clauses.append("(n.ref_norm = ? OR n.name_lower = ?)")
                sub_params.extend([ref_norm, name])
            elif ref_norm:
                sub_clauses.append("n.ref_norm = ?")
                sub_params.append(ref_norm)
            elif name:
                sub_clauses.append("n.name_lower = ?")
                sub_params.append(name)
            else:
                continue
            base_clauses.append(f"EXISTS (SELECT 1 FROM image_nodes n WHERE {' AND '.join(sub_clauses)})")
            base_params.extend(sub_params)

        for term in q.strip().lower().split():
            like = f"%{term}%"
            base_clauses.append(
                "("
                "LOWER(i.filename) LIKE ? OR LOWER(i.group_name) LIKE ? OR "
                "LOWER(COALESCE(i.backend, '')) LIKE ? OR LOWER(COALESCE(i.seed, '')) LIKE ? OR "
                "EXISTS (SELECT 1 FROM image_nodes nq WHERE nq.path = i.path AND nq.name_lower LIKE ?)"
                ")"
            )
            base_params.extend([like, like, like, like, like])

        kind_clean = kind.strip().lower()
        if kind_clean and kind_clean != "all":
            if kind_clean == "sequential":
                base_clauses.append("i.run_kind IN ('sequential', 'sequential-all')")
            else:
                base_clauses.append("i.run_kind = ?")
                base_params.append(kind_clean)

        # backends 统计不含 backend 条件本身，这样选中一个后端后还能切回其他后端。
        backends_where = f"WHERE {' AND '.join(base_clauses)}" if base_clauses else ""

        backend_clean = backend.strip()
        if backend_clean and backend_clean != "all":
            base_clauses.append("i.backend = ?")
            base_params.append(backend_clean)

        # matched_runs 统计不含 run_id 条件，这样侧边栏始终能看到所有命中批次并切换。
        runs_where = f"WHERE {' AND '.join(base_clauses)}" if base_clauses else ""
        runs_params = list(base_params)

        full_clauses = list(base_clauses)
        full_params = list(base_params)
        if run_id.strip():
            full_clauses.append("i.run_id = ?")
            full_params.append(run_id.strip())
        full_where = f"WHERE {' AND '.join(full_clauses)}" if full_clauses else ""

        with self._lock:
            backend_rows = self._conn.execute(
                f"SELECT DISTINCT i.backend FROM images i {backends_where} "
                f"{'AND' if backends_where else 'WHERE'} i.backend IS NOT NULL AND i.backend != '' "
                f"ORDER BY i.backend",
                base_params[: len(base_params) - (1 if backend_clean and backend_clean != "all" else 0)],
            ).fetchall()
            matched_run_rows = self._conn.execute(
                f"SELECT i.run_id, COUNT(*) AS match_count FROM images i {runs_where} GROUP BY i.run_id",
                runs_params,
            ).fetchall()
            total = self._conn.execute(
                f"SELECT COUNT(*) AS cnt FROM images i {full_where}",
                full_params,
            ).fetchone()["cnt"]
            image_rows = self._conn.execute(
                f"""
                SELECT
                    i.path, i.run_id, i.run_name, i.run_kind, i.filename, i.group_name,
                    i.created_at, i.size_bytes, i.backend, i.seed, i.width, i.height,
                    i.timing_json, i.nodes_json
                FROM images i
                {full_where}
                ORDER BY i.created_at DESC, i.filename ASC
                LIMIT ? OFFSET ?
                """,
                [*full_params, limit, offset],
            ).fetchall()

        images = [self._row_to_image(row) for row in image_rows]
        return {
            "schema": "tags-machine-core.web.history-search/v1",
            "total": int(total),
            "offset": offset,
            "limit": limit,
            "indexing": self.indexing_status(),
            "backends": [row["backend"] for row in backend_rows],
            "matched_runs": [
                {"id": row["run_id"], "match_count": int(row["match_count"])}
                for row in matched_run_rows
            ],
            "images": images,
        }

    def list_nodes(self, *, role: str = "", q: str = "", limit: int = 100) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        role_clean = role.strip().lower()
        if role_clean and role_clean != "all":
            clauses.append("role = ?")
            params.append(role_clean)
        q_clean = q.strip().lower()
        if q_clean:
            like = f"%{q_clean}%"
            clauses.append("(name_lower LIKE ? OR COALESCE(ref_norm, '') LIKE ?)")
            params.extend([like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT
                    role,
                    MIN(name) AS name,
                    MAX(ref) AS ref,
                    COUNT(DISTINCT path) AS count
                FROM image_nodes
                {where}
                GROUP BY role, name_lower
                ORDER BY count DESC, name ASC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        return {
            "schema": "tags-machine-core.web.history-nodes/v1",
            "indexing": self.indexing_status(),
            "nodes": [
                {
                    "role": row["role"],
                    "name": row["name"],
                    "ref": row["ref"],
                    "count": int(row["count"]),
                }
                for row in rows
            ],
        }

    def _row_to_image(self, row: sqlite3.Row) -> dict[str, Any]:
        seed_raw = row["seed"]
        seed: int | str | None = None
        if seed_raw is not None:
            try:
                seed = int(seed_raw)
            except ValueError:
                seed = seed_raw
        return {
            "path": row["path"],
            "run_id": row["run_id"],
            "run_name": row["run_name"],
            "run_kind": row["run_kind"],
            "filename": row["filename"],
            "group": row["group_name"],
            "created_at": row["created_at"],
            "size_bytes": row["size_bytes"],
            "info": {
                "backend": row["backend"],
                "seed": seed,
                "width": row["width"],
                "height": row["height"],
                "nodes": json.loads(row["nodes_json"]) if row["nodes_json"] else [],
                "timing": json.loads(row["timing_json"]) if row["timing_json"] else None,
            },
        }
