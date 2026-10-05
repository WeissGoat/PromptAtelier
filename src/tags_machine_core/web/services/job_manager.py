from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


JobStatus = Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled", "interrupted"]
TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
# 磁盘上最多保留的任务记录数；更早的记录文件会被删掉（图片本身不动）。
MAX_PERSISTED_JOBS = 200
# 只有结果快照变化时，同一任务两次写盘至少间隔这么久；状态变化总是立即写。
_PERSIST_INTERVAL_SECONDS = 2.0
_EVENT_LIMIT = 200

logger = logging.getLogger(__name__)


@dataclass
class JobRecord:
    id: str
    name: str
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: Any = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    # 提交时的原始请求，用于"继续剩余项"；单独存文件，不随轮询返回。
    request: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tags-machine-core.web.job/v1",
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
            "events": self.events[-_EVENT_LIMIT:],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobRecord":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            status=data.get("status") or "failed",
            created_at=float(data.get("created_at") or 0),
            updated_at=float(data.get("updated_at") or 0),
            result=data.get("result"),
            error=data.get("error"),
            events=list(data.get("events") or []),
        )


class JobContext:
    def __init__(self, manager: "JobManager", job_id: str):
        self.manager = manager
        self.job_id = job_id

    @property
    def cancel_requested(self) -> bool:
        return self.manager.get(self.job_id).status == "cancelling"

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.manager.emit(self.job_id, event_type, payload)

    def set_result(self, result: Any) -> None:
        """运行中先公开一份阶段性结果（如后台批量的逐项进度）；任务结束时以 worker 的返回值为准。"""
        self.manager._update(self.job_id, result=result)


class JobManager:
    """后台任务。给了 persist_dir 时，persist_names 里的任务会写盘，后端重启后还能看到。

    重启时还没跑完的任务标成 interrupted，可以用 resume 在原任务上继续。
    """

    def __init__(
        self,
        *,
        persist_dir: str | Path | None = None,
        persist_names: Collection[str] = (),
        recover: Callable[[JobRecord], None] | None = None,
    ):
        self._jobs: dict[str, JobRecord] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._persist_dir = Path(persist_dir) if persist_dir else None
        self._persist_names = frozenset(persist_names)
        self._last_persisted: dict[str, float] = {}
        if self._persist_dir is not None:
            self._load(recover)

    def submit(self, name: str, worker: Callable[[JobContext], Any], *, request: Any = None) -> JobRecord:
        job = JobRecord(id=uuid.uuid4().hex[:12], name=name, request=request)
        with self._lock:
            self._jobs[job.id] = job
            if request is not None and self._persist_dir is not None and name in self._persist_names:
                self._write_json(self._request_path(job.id), request)
            self._persist(job)
            self._prune()
        self._start(job.id, worker)
        return job

    def resume(self, job_id: str, worker: Callable[[JobContext], Any]) -> JobRecord:
        """在原任务上重新开跑（worker 自己决定跳过哪些已完成的部分）。"""
        with self._lock:
            job = self.get(job_id)
            if job.status not in TERMINAL_STATUSES:
                raise ValueError(f"job {job_id} is still {job.status}")
            self._update(job_id, status="queued", error=None)
        self._start(job_id, worker)
        return self.get(job_id)

    def request_of(self, job_id: str) -> Any:
        job = self.get(job_id)
        if job.request is None and self._persist_dir is not None:
            path = self._request_path(job_id)
            if path.is_file():
                job.request = json.loads(path.read_text(encoding="utf-8"))
        return job.request

    def _start(self, job_id: str, worker: Callable[[JobContext], Any]) -> None:
        thread = threading.Thread(target=self._run, args=(job_id, worker), daemon=True)
        self._threads[job_id] = thread
        thread.start()

    def _run(self, job_id: str, worker: Callable[[JobContext], Any]) -> None:
        if self.get(job_id).status != "cancelling":
            self._update(job_id, status="running")
        self.emit(job_id, "started", {})
        try:
            result = worker(JobContext(self, job_id))
            current = self.get(job_id)
            final_status: JobStatus = "cancelled" if current.status == "cancelling" else "succeeded"
            self._update(job_id, status=final_status, result=result)
            self.emit(job_id, final_status, {})
        except Exception as exc:
            self._update(job_id, status="failed", error=str(exc))
            self.emit(job_id, "failed", {"error": str(exc)})

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._jobs[job_id]

    def list(self, *, name: str | None = None, limit: int = 20) -> list[JobRecord]:
        """最新的在前。"""
        with self._lock:
            jobs = [job for job in self._jobs.values() if name is None or job.name == name]
        jobs.sort(key=lambda job: job.created_at, reverse=True)
        return jobs[:limit]

    def cancel(self, job_id: str) -> JobRecord:
        self._update(job_id, status="cancelling")
        self.emit(job_id, "cancelling", {})
        return self.get(job_id)

    def emit(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        # 事件只在内存里累积，跟着下一次状态 / 结果更新一起写盘，避免进度事件频繁写文件。
        with self._lock:
            job = self.get(job_id)
            event = {"type": event_type, **payload}
            job.events.append(event)
            if len(job.events) > _EVENT_LIMIT * 2:
                del job.events[:-_EVENT_LIMIT]
            job.updated_at = time.time()

    def wait(self, job_id: str, timeout: float) -> None:
        thread = self._threads[job_id]
        thread.join(timeout=timeout)

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self.get(job_id)
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = time.time()
            throttled = "status" not in changes and job.status not in TERMINAL_STATUSES
            if not throttled or job.updated_at - self._last_persisted.get(job_id, 0) >= _PERSIST_INTERVAL_SECONDS:
                self._persist(job)

    # ---- 持久化 ----

    def _job_path(self, job_id: str) -> Path:
        assert self._persist_dir is not None
        return self._persist_dir / f"{job_id}.json"

    def _request_path(self, job_id: str) -> Path:
        assert self._persist_dir is not None
        return self._persist_dir / f"{job_id}.request.json"

    def _persist(self, job: JobRecord) -> None:
        if self._persist_dir is None or job.name not in self._persist_names:
            return
        try:
            self._write_json(self._job_path(job.id), job.to_dict())
            self._last_persisted[job.id] = time.time()
        except (OSError, TypeError, ValueError) as exc:  # 写盘失败不影响任务本身
            logger.warning("failed to persist job %s: %s", job.id, exc)

    def _write_json(self, path: Path, data: Any) -> None:
        if self._persist_dir is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)

    def _load(self, recover: Callable[[JobRecord], None] | None) -> None:
        assert self._persist_dir is not None
        if not self._persist_dir.is_dir():
            return
        for path in self._persist_dir.glob("*.json"):
            if path.name.endswith(".request.json"):
                continue
            try:
                job = JobRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning("skipping unreadable job record %s: %s", path, exc)
                continue
            if job.status not in TERMINAL_STATUSES:
                # 上次后端退出时还在跑；只改内存，不回写，免得测试或第二个进程改动正在跑的记录。
                job.status = "interrupted"
                if recover is not None:
                    recover(job)
            self._jobs[job.id] = job

    def _prune(self) -> None:
        if self._persist_dir is None:
            return
        persisted = [job for job in self._jobs.values() if job.name in self._persist_names]
        if len(persisted) <= MAX_PERSISTED_JOBS:
            return
        persisted.sort(key=lambda job: job.created_at, reverse=True)
        for job in persisted[MAX_PERSISTED_JOBS:]:
            if job.status not in TERMINAL_STATUSES:
                continue
            self._jobs.pop(job.id, None)
            for path in (self._job_path(job.id), self._request_path(job.id)):
                path.unlink(missing_ok=True)
