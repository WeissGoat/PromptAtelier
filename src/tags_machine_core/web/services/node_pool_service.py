from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from tags_machine_core.node_pools import (
    NodePoolResolver,
    NodePoolScanResult,
    NodePoolSpec,
    ProjectCollectionLoader,
)

from .node_workspace import NodeWorkspace


VALID_ROLES = {"artist", "character", "action", "background"}


@dataclass
class _CacheEntry:
    created_at: float
    result: NodePoolScanResult


class NodePoolService:
    def __init__(
        self,
        *,
        workspace: NodeWorkspace,
        project_requires: list[str],
        base_dir: str | Path,
        cache_ttl_seconds: float = 300.0,
    ):
        self.workspace = workspace
        self.project_loader = ProjectCollectionLoader(project_requires, base_dir=base_dir)
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = RLock()

    def collections(self, role: str) -> list[dict[str, Any]]:
        self._validate_role(role)
        values = self.project_loader.load().get(f"{role}s", {})
        return [
            {"name": name, "item_count": len(items) if isinstance(items, list) else 0}
            for name, items in sorted(values.items())
        ]

    def scan(
        self,
        *,
        role: str,
        spec: NodePoolSpec,
        query: str | None = None,
        offset: int = 0,
        limit: int = 20,
        refresh: bool = False,
    ) -> dict[str, Any]:
        self._validate_role(role)
        offset = max(0, offset)
        limit = max(1, min(limit, 200))
        cache_key = self._cache_key(role, spec)
        result = None if refresh else self._cached(cache_key)
        if result is None:
            result = self._resolver().scan(role, spec)
            with self._lock:
                self._cache[cache_key] = _CacheEntry(created_at=time.time(), result=result)
        needle = (query or "").strip().lower()
        filtered = [
            item
            for item in result.candidates
            if not needle or needle in f"{item.name} {item.ref} {item.relative or ''}".lower()
        ]
        page = filtered[offset : offset + limit]
        return {
            "schema": "tags-machine-core.web.node-pool-scan/v1",
            "scan_id": cache_key[:16],
            "role": role,
            "total": len(filtered),
            "source_total": result.stats.total,
            "items": [item.model_dump(mode="json") for item in page],
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < len(filtered),
            "next_offset": offset + len(page) if offset + len(page) < len(filtered) else None,
            "stats": result.stats.model_dump(mode="json"),
            "facets": result.facets,
            "warnings": result.warnings,
        }

    def sample(self, *, role: str, spec: NodePoolSpec, count: int) -> dict[str, Any]:
        self._validate_role(role)
        result = self._resolver().sample(role, spec, count)
        return {
            "schema": "tags-machine-core.web.node-pool-sample/v1",
            "role": role,
            "items": [item.model_dump(mode="json") for item in result.items],
            "stats": result.stats.model_dump(mode="json"),
        }

    def _resolver(self) -> NodePoolResolver:
        return NodePoolResolver(
            design_root=self.workspace.design_root,
            collections=self.project_loader.load(),
            node_loader=lambda role, ref: {
                "node": self.workspace.read_runtime_node(ref, role=role).model_dump(mode="json")
            },
        )

    def _cached(self, key: str) -> NodePoolScanResult | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.time() - entry.created_at > self.cache_ttl_seconds:
                self._cache.pop(key, None)
                return None
            return entry.result

    @staticmethod
    def _cache_key(role: str, spec: NodePoolSpec) -> str:
        payload = json.dumps(
            {"role": role, "spec": spec.model_dump(mode="json")},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in VALID_ROLES:
            raise ValueError(f"unsupported random node role: {role}")
