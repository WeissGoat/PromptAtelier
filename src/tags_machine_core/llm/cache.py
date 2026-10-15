from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


def cache_key(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LLMCache:
    """LLM 结果缓存：同一输入的结果保持稳定，界面不会每次刷新都换一个说法。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS llm_cache ("
            "key TEXT PRIMARY KEY, task TEXT NOT NULL, model TEXT, value TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM llm_cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        found: dict[str, Any] = {}
        with self._lock:
            for start in range(0, len(keys), 500):
                chunk = keys[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = self._conn.execute(
                    f"SELECT key, value FROM llm_cache WHERE key IN ({placeholders})", chunk
                ).fetchall()
                found.update({key: json.loads(value) for key, value in rows})
        return found

    def set(self, key: str, value: Any, *, task: str, model: str | None) -> None:
        self.set_many([(key, value)], task=task, model=model)

    def set_many(self, items: list[tuple[str, Any]], *, task: str, model: str | None) -> None:
        now = time.time()
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO llm_cache (key, task, model, value, created_at) VALUES (?, ?, ?, ?, ?)",
                [(key, task, model, json.dumps(value, ensure_ascii=False), now) for key, value in items],
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
