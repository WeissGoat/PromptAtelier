from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from pydantic import BaseModel

from ..catalog import CatalogRepository
from ..models import utc_now_iso


LOCK_NAME = "publishing_import"


class WorkspaceLease(BaseModel):
    lock_name: str
    owner_run_id: str
    owner_token: str
    lease_expires_at: str
    updated_at: str


class WorkspaceLeaseRepository:
    def __init__(
        self,
        catalog: CatalogRepository,
        *,
        lease_seconds: int = 90,
        now: Callable[[], datetime] | None = None,
    ):
        self.catalog = catalog
        self.lease_seconds = lease_seconds
        self.now = now or (lambda: datetime.now(timezone.utc))

    def acquire(self, run_id: str, *, allow_takeover: bool) -> WorkspaceLease:
        current = self.now()
        expires = current + timedelta(seconds=self.lease_seconds)
        with self.catalog.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM workspace_locks WHERE lock_name=?", (LOCK_NAME,)
            ).fetchone()
            if row is not None:
                old_expires = datetime.fromisoformat(row["lease_expires_at"])
                if old_expires > current:
                    raise RuntimeError(
                        f"workspace 正被 ImportRun {row['owner_run_id']} 使用"
                    )
                if not allow_takeover:
                    raise RuntimeError("workspace 租约已过期，需要 resume 接管")
                if row["owner_run_id"] != run_id:
                    raise RuntimeError(
                        f"过期租约属于 ImportRun {row['owner_run_id']}，只能由该 Run resume 接管"
                    )
            token = row["owner_token"] if row is not None and row["owner_run_id"] == run_id else uuid4().hex
            updated = utc_now_iso()
            connection.execute(
                "INSERT INTO workspace_locks(lock_name, owner_run_id, owner_token, "
                "lease_expires_at, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(lock_name) DO UPDATE SET owner_run_id=excluded.owner_run_id, "
                "owner_token=excluded.owner_token, lease_expires_at=excluded.lease_expires_at, "
                "updated_at=excluded.updated_at",
                (LOCK_NAME, run_id, token, expires.isoformat(), updated),
            )
        return WorkspaceLease(
            lock_name=LOCK_NAME,
            owner_run_id=run_id,
            owner_token=token,
            lease_expires_at=expires.isoformat(),
            updated_at=updated,
        )

    def refresh(self, connection: sqlite3.Connection, lease: WorkspaceLease) -> WorkspaceLease:
        current = self.now()
        expires = current + timedelta(seconds=self.lease_seconds)
        cursor = connection.execute(
            "UPDATE workspace_locks SET lease_expires_at=?, updated_at=? "
            "WHERE lock_name=? AND owner_run_id=? AND owner_token=?",
            (
                expires.isoformat(),
                utc_now_iso(),
                lease.lock_name,
                lease.owner_run_id,
                lease.owner_token,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("刷新 workspace 租约失败，当前 Run 不能继续")
        return lease.model_copy(
            update={"lease_expires_at": expires.isoformat(), "updated_at": utc_now_iso()}
        )

    def release(self, lease: WorkspaceLease) -> None:
        with self.catalog.connection() as connection:
            connection.execute(
                "DELETE FROM workspace_locks WHERE lock_name=? AND owner_run_id=? AND owner_token=?",
                (lease.lock_name, lease.owner_run_id, lease.owner_token),
            )
