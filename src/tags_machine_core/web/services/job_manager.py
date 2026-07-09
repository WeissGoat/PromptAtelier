from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


JobStatus = Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]


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
            "events": self.events[-200:],
        }


class JobContext:
    def __init__(self, manager: "JobManager", job_id: str):
        self.manager = manager
        self.job_id = job_id

    @property
    def cancel_requested(self) -> bool:
        return self.manager.get(self.job_id).status == "cancelling"

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.manager.emit(self.job_id, event_type, payload)


class JobManager:
    def __init__(self):
        self._jobs: dict[str, JobRecord] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    def submit(self, name: str, worker: Callable[[JobContext], Any]) -> JobRecord:
        job = JobRecord(id=uuid.uuid4().hex[:12], name=name)
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job.id, worker), daemon=True)
        self._threads[job.id] = thread
        thread.start()
        return job

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

    def cancel(self, job_id: str) -> JobRecord:
        self._update(job_id, status="cancelling")
        self.emit(job_id, "cancelling", {})
        return self.get(job_id)

    def emit(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock:
            job = self.get(job_id)
            event = {"type": event_type, **payload}
            job.events.append(event)
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
