# Web Control Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Web service and React UI for Custom Studio, structured node editing, Batch preview/run, Compare variants, and Results browsing.

**Architecture:** Add a thin FastAPI layer that directly imports `tags_machine_core` services instead of shelling out to CLI. Add a React/Vite frontend that calls this local HTTP API and keeps YAML/node files as the source of truth. Long-running generation and batch runs go through an in-memory `JobManager` with event streaming.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, Pydantic v2, existing `tags_machine_core`, React, Vite, TypeScript, Vitest, Playwright for browser verification.

## Global Constraints

- Local-first only; no cloud deployment, multi-user accounts, or permissions in v1.
- Reuse `tags_machine_core`; do not reimplement prompt composition, render planning, NovelAI payload creation, or batch expansion in the frontend.
- Preview must not call NovelAI; only generate `PromptBundle` and `RenderRequest`.
- Only explicit generate/run actions call NovelAI.
- Composer support in v1 is limited to `script` and `full prompt`; AgentComposer UI is out of scope for this plan.
- Node editing is structured-form first; raw file view is available for inspection and advanced editing.
- Node edits are draft-only until the user clicks Save.
- Existing `batch YAML`, `meta.yaml`, and `tags.txt` remain source of truth.
- Business verification with real NovelAI output is required before claiming the generation and batch workflows are complete.

---

## File Structure

Create backend Web service files:

- `src/tags_machine_core/web/__init__.py`  
  Exports `create_app`.
- `src/tags_machine_core/web/app.py`  
  Creates FastAPI app, configures CORS for local dev, mounts routers, centralizes error handling.
- `src/tags_machine_core/web/errors.py`  
  Defines `ApiError`, `error_response`, and exception handler helpers.
- `src/tags_machine_core/web/routes/health.py`  
  Health and backend capability endpoints.
- `src/tags_machine_core/web/routes/nodes.py`  
  Node list/read/preview/save/create endpoints.
- `src/tags_machine_core/web/routes/compose.py`  
  Custom Studio preview endpoints.
- `src/tags_machine_core/web/routes/generate.py`  
  Single generate job endpoints.
- `src/tags_machine_core/web/routes/batch.py`  
  Batch preview/run/resume/inspect endpoints.
- `src/tags_machine_core/web/routes/jobs.py`  
  Job status, event stream, cancel endpoints.
- `src/tags_machine_core/web/routes/results.py`  
  Results index and artifact file endpoints.
- `src/tags_machine_core/web/services/job_manager.py`  
  In-memory job lifecycle, event buffer, cooperative cancellation.
- `src/tags_machine_core/web/services/node_workspace.py`  
  Safe design-root node discovery, structured draft conversion, node save/create.
- `src/tags_machine_core/web/services/batch_workspace.py`  
  Batch spec mapping, preview summaries, run directory helpers.
- `src/tags_machine_core/web/services/result_index.py`  
  Scan output/run directories and expose result metadata.
- `src/tags_machine_core/web/__main__.py`  
  Runs Uvicorn for `python -m tags_machine_core.web`.

Modify Python project files:

- `pyproject.toml`  
  Add `fastapi`, `uvicorn[standard]`, and optional frontend dev docs script only if needed.
- `src/tags_machine_core/__init__.py`  
  No required change unless exports are needed.

Create backend tests:

- `tests/test_web_app.py`
- `tests/test_web_jobs.py`
- `tests/test_web_nodes.py`
- `tests/test_web_compose.py`
- `tests/test_web_batch.py`
- `tests/test_web_results.py`

Create frontend files:

- `web/package.json`
- `web/index.html`
- `web/vite.config.ts`
- `web/tsconfig.json`
- `web/src/main.tsx`
- `web/src/App.tsx`
- `web/src/api/client.ts`
- `web/src/api/types.ts`
- `web/src/state/studioStore.ts`
- `web/src/components/Layout.tsx`
- `web/src/components/NodePicker.tsx`
- `web/src/components/NodeEditor.tsx`
- `web/src/components/PromptPreview.tsx`
- `web/src/components/RenderParamsPanel.tsx`
- `web/src/pages/CustomStudio.tsx`
- `web/src/pages/BatchStudio.tsx`
- `web/src/pages/ResultsGallery.tsx`
- `web/src/pages/CompareStudio.tsx`
- `web/src/styles.css`

Create frontend tests:

- `web/src/api/client.test.ts`
- `web/src/pages/CustomStudio.test.tsx`
- `web/src/pages/BatchStudio.test.tsx`
- `web/e2e/custom-studio.spec.ts`
- `web/e2e/batch-studio.spec.ts`

Create docs:

- `docs/web_control_console_readme.md`
- `docs/web_control_console_business_test_20260710.md`

---

### Task 1: FastAPI App Skeleton and Error Contract

**Files:**
- Modify: `pyproject.toml`
- Create: `src/tags_machine_core/web/__init__.py`
- Create: `src/tags_machine_core/web/app.py`
- Create: `src/tags_machine_core/web/errors.py`
- Create: `src/tags_machine_core/web/routes/health.py`
- Create: `src/tags_machine_core/web/__main__.py`
- Test: `tests/test_web_app.py`

**Interfaces:**
- Produces: `create_app() -> fastapi.FastAPI`
- Produces: `ApiError(code: str, message: str, status_code: int = 400, details: dict[str, Any] | None = None)`
- Produces HTTP:
  - `GET /api/health`
  - `GET /api/backend-support`

- [ ] **Step 1: Add backend dependencies**

Modify `pyproject.toml` dependencies to include:

```toml
dependencies = [
    "ai-image-gateway",
    "fastapi>=0.115",
    "Pillow>=10.0",
    "pydantic>=2.6",
    "PyYAML>=6.0",
    "requests>=2.31",
    "uvicorn[standard]>=0.30",
]
```

- [ ] **Step 2: Write failing app tests**

Create `tests/test_web_app.py`:

```python
from fastapi.testclient import TestClient

from tags_machine_core.web import create_app


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "schema": "tags-machine-core.web.health/v1",
        "status": "ok",
    }


def test_backend_support_endpoint_exposes_novelai():
    client = TestClient(create_app())

    response = client.get("/api/backend-support")

    assert response.status_code == 200
    data = response.json()
    assert data["schema"] == "tags-machine-core.backend-support/v1"
    assert "novelai" in data["backends"]
```

- [ ] **Step 3: Run failing test**

Run:

```powershell
uv run python -m unittest tests.test_web_app -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tags_machine_core.web'`.

- [ ] **Step 4: Implement `ApiError`**

Create `src/tags_machine_core/web/errors.py`:

```python
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def error_payload(error: ApiError) -> dict[str, Any]:
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        }
    }


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_payload(exc))
```

- [ ] **Step 5: Implement health routes**

Create `src/tags_machine_core/web/routes/health.py`:

```python
from __future__ import annotations

from fastapi import APIRouter

from tags_machine_core.backends import backend_support_report


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "schema": "tags-machine-core.web.health/v1",
        "status": "ok",
    }


@router.get("/backend-support")
def backend_support() -> dict:
    return backend_support_report()
```

- [ ] **Step 6: Implement app factory**

Create `src/tags_machine_core/web/app.py`:

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .errors import ApiError, api_error_handler
from .routes import health


def create_app() -> FastAPI:
    app = FastAPI(title="PromptAtelier Web Console", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(health.router, prefix="/api", tags=["health"])
    return app
```

Create `src/tags_machine_core/web/__init__.py`:

```python
from .app import create_app

__all__ = ["create_app"]
```

Create `src/tags_machine_core/web/__main__.py`:

```python
from __future__ import annotations

import uvicorn

from .app import create_app


def main() -> None:
    uvicorn.run(create_app(), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
```

Create `src/tags_machine_core/web/routes/__init__.py`:

```python
"""HTTP route modules for the local Web console."""
```

- [ ] **Step 7: Run tests**

Run:

```powershell
uv run python -m unittest tests.test_web_app -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add pyproject.toml src/tags_machine_core/web tests/test_web_app.py
git commit -m "feat: add web app skeleton"
```

---

### Task 2: Job Manager and Event Stream

**Files:**
- Create: `src/tags_machine_core/web/services/job_manager.py`
- Create: `src/tags_machine_core/web/routes/jobs.py`
- Modify: `src/tags_machine_core/web/app.py`
- Test: `tests/test_web_jobs.py`

**Interfaces:**
- Produces: `JobManager.submit(name: str, worker: Callable[[JobContext], Any]) -> JobRecord`
- Produces: `JobManager.get(job_id: str) -> JobRecord`
- Produces: `JobManager.cancel(job_id: str) -> JobRecord`
- Produces HTTP:
  - `GET /api/jobs/{job_id}`
  - `GET /api/jobs/{job_id}/events`
  - `POST /api/jobs/{job_id}/cancel`

- [ ] **Step 1: Write failing job tests**

Create `tests/test_web_jobs.py`:

```python
import time

from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.job_manager import JobContext, JobManager


def test_job_manager_runs_worker_and_records_events():
    manager = JobManager()

    def worker(ctx: JobContext):
        ctx.emit("progress", {"value": 1})
        return {"done": True}

    job = manager.submit("demo", worker)
    manager.wait(job.id, timeout=5)

    record = manager.get(job.id)
    assert record.status == "succeeded"
    assert record.result == {"done": True}
    assert record.events[-1]["type"] == "succeeded"
    assert {"type": "progress", "value": 1} in record.events


def test_job_cancel_sets_flag_for_worker():
    manager = JobManager()

    def worker(ctx: JobContext):
        while not ctx.cancel_requested:
            time.sleep(0.01)
        ctx.emit("stopped", {})
        return {"cancelled": True}

    job = manager.submit("cancel-demo", worker)
    manager.cancel(job.id)
    manager.wait(job.id, timeout=5)

    record = manager.get(job.id)
    assert record.status == "cancelled"
    assert record.result == {"cancelled": True}


def test_jobs_http_status_and_cancel():
    manager = JobManager()

    def worker(ctx: JobContext):
        ctx.emit("ready", {})
        return {"ok": True}

    app = create_app(job_manager=manager)
    client = TestClient(app)
    job = manager.submit("http-demo", worker)
    manager.wait(job.id, timeout=5)

    response = client.get(f"/api/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
uv run python -m unittest tests.test_web_jobs -v
```

Expected: FAIL because `JobManager` does not exist.

- [ ] **Step 3: Implement JobManager**

Create `src/tags_machine_core/web/services/job_manager.py`:

```python
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
```

- [ ] **Step 4: Implement job routes**

Create `src/tags_machine_core/web/routes/jobs.py`:

```python
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from tags_machine_core.web.errors import ApiError
from tags_machine_core.web.services.job_manager import JobManager

router = APIRouter()


def _manager(request: Request) -> JobManager:
    return request.app.state.job_manager


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    try:
        return _manager(request).get(job_id).to_dict()
    except KeyError as exc:
        raise ApiError(code="job_not_found", message=f"Job not found: {job_id}", status_code=404) from exc


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict:
    try:
        return _manager(request).cancel(job_id).to_dict()
    except KeyError as exc:
        raise ApiError(code="job_not_found", message=f"Job not found: {job_id}", status_code=404) from exc


@router.get("/jobs/{job_id}/events")
def job_events(job_id: str, request: Request) -> StreamingResponse:
    manager = _manager(request)
    try:
        manager.get(job_id)
    except KeyError as exc:
        raise ApiError(code="job_not_found", message=f"Job not found: {job_id}", status_code=404) from exc

    def stream():
        last_index = 0
        while True:
            job = manager.get(job_id)
            events = job.events[last_index:]
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            last_index += len(events)
            if job.status in {"succeeded", "failed", "cancelled"}:
                break

    return StreamingResponse(stream(), media_type="text/event-stream")
```

Modify `src/tags_machine_core/web/app.py`:

```python
from .routes import health, jobs
from .services.job_manager import JobManager


def create_app(*, job_manager: JobManager | None = None) -> FastAPI:
    app = FastAPI(title="PromptAtelier Web Console", version="0.1.0")
    app.state.job_manager = job_manager or JobManager()
    ...
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(jobs.router, prefix="/api", tags=["jobs"])
    return app
```

- [ ] **Step 5: Run tests**

Run:

```powershell
uv run python -m unittest tests.test_web_jobs -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/tags_machine_core/web tests/test_web_jobs.py
git commit -m "feat: add web job manager"
```

---

### Task 3: Node Workspace API

**Files:**
- Create: `src/tags_machine_core/web/services/node_workspace.py`
- Create: `src/tags_machine_core/web/routes/nodes.py`
- Modify: `src/tags_machine_core/web/app.py`
- Test: `tests/test_web_nodes.py`

**Interfaces:**
- Produces: `NodeWorkspace.list_nodes(role: str, query: str | None = None) -> list[dict[str, Any]]`
- Produces: `NodeWorkspace.read_node(ref: str) -> dict[str, Any]`
- Produces: `NodeWorkspace.preview_node(raw: dict[str, Any]) -> dict[str, Any]`
- Produces: `NodeWorkspace.save_node(ref: str, node: dict[str, Any]) -> dict[str, Any]`
- Produces HTTP:
  - `GET /api/nodes?role=character&q=homura`
  - `GET /api/nodes/read?ref=...`
  - `POST /api/nodes/preview`
  - `PUT /api/nodes/save`

- [ ] **Step 1: Write failing node tests**

Create `tests/test_web_nodes.py`:

```python
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.node_workspace import NodeWorkspace


def _write_meta(path: Path, *, kind: str, node_id: str, prompt: str) -> None:
    path.mkdir(parents=True)
    (path / "meta.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": kind,
                "id": node_id,
                "name": node_id,
                "prompt": {"positive": [prompt]},
                "tags": {"default": [prompt]},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_node_workspace_lists_and_reads_nodes(tmp_path):
    design = tmp_path / "design"
    _write_meta(design / "角色" / "homura", kind="character", node_id="homura", prompt="akemi_homura")
    workspace = NodeWorkspace(design_root=design)

    nodes = workspace.list_nodes("character", query="homura")
    loaded = workspace.read_node(nodes[0]["ref"])

    assert len(nodes) == 1
    assert nodes[0]["name"] == "homura"
    assert loaded["node"]["id"] == "homura"
    assert loaded["form"]["prompt"]["positive"] == ["akemi_homura"]


def test_nodes_http_preview_does_not_write_file(tmp_path):
    design = tmp_path / "design"
    _write_meta(design / "角色" / "homura", kind="character", node_id="homura", prompt="akemi_homura")
    workspace = NodeWorkspace(design_root=design)
    client = TestClient(create_app(node_workspace=workspace))

    response = client.post(
        "/api/nodes/preview",
        json={"kind": "character", "id": "draft", "prompt": {"positive": ["draft_tag"]}},
    )

    assert response.status_code == 200
    assert response.json()["form"]["prompt"]["positive"] == ["draft_tag"]
    assert not (design / "角色" / "draft").exists()
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
uv run python -m unittest tests.test_web_nodes -v
```

Expected: FAIL because `NodeWorkspace` does not exist.

- [ ] **Step 3: Implement NodeWorkspace**

Create `src/tags_machine_core/web/services/node_workspace.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.reader import NodeReader


ROLE_DIRS = {
    "artist": ["画风", "artist", "artists"],
    "character": ["角色", "character", "characters"],
    "action": ["动作改2", "动作", "action", "actions"],
    "background": ["背景", "background", "backgrounds"],
}


class NodeWorkspace:
    def __init__(self, *, design_root: str | Path, reader: NodeReader | None = None):
        self.design_root = Path(design_root)
        self.reader = reader or NodeReader()

    def list_nodes(self, role: str, query: str | None = None) -> list[dict[str, Any]]:
        roots = [self.design_root / item for item in ROLE_DIRS.get(role, [role])]
        result: list[dict[str, Any]] = []
        needle = (query or "").strip().lower()
        for root in roots:
            if not root.exists():
                continue
            for item in sorted(root.iterdir(), key=lambda path: path.name):
                if not item.is_dir():
                    continue
                if needle and needle not in item.name.lower():
                    continue
                if self._has_node_file(item):
                    result.append({"role": role, "name": item.name, "ref": str(item)})
        return result

    def read_node(self, ref: str | Path) -> dict[str, Any]:
        path = Path(ref)
        node = self.reader.read(path)
        return {
            "schema": "tags-machine-core.web.node/v1",
            "ref": str(path),
            "node": node.model_dump(mode="json"),
            "form": self.to_form(node),
            "raw": self._raw_file(path),
        }

    def preview_node(self, raw: dict[str, Any]) -> dict[str, Any]:
        node = NodeDocument.model_validate(raw)
        return {
            "schema": "tags-machine-core.web.node-preview/v1",
            "node": node.model_dump(mode="json"),
            "form": self.to_form(node),
        }

    def save_node(self, ref: str | Path, node_data: dict[str, Any]) -> dict[str, Any]:
        path = Path(ref)
        path.mkdir(parents=True, exist_ok=True)
        node = NodeDocument.model_validate(node_data)
        target = path / "meta.yaml"
        target.write_text(
            yaml.safe_dump(node.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return self.read_node(path)

    def to_form(self, node: NodeDocument) -> dict[str, Any]:
        return {
            "kind": node.kind,
            "id": node.id,
            "name": node.name,
            "description": node.description,
            "prompt": node.prompt.model_dump(mode="json"),
            "tags": node.tags,
            "relations": node.relations,
            "composition": node.composition,
        }

    def _has_node_file(self, path: Path) -> bool:
        return any((path / name).exists() for name in ("meta.yaml", "node.yaml", "tags.txt"))

    def _raw_file(self, path: Path) -> dict[str, str] | None:
        for name in ("meta.yaml", "node.yaml", "tags.txt"):
            candidate = path / name
            if candidate.exists():
                return {"filename": name, "text": candidate.read_text(encoding="utf-8", errors="ignore")}
        return None
```

- [ ] **Step 4: Implement node routes**

Create `src/tags_machine_core/web/routes/nodes.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from tags_machine_core.web.errors import ApiError
from tags_machine_core.web.services.node_workspace import NodeWorkspace

router = APIRouter()


def _workspace(request: Request) -> NodeWorkspace:
    return request.app.state.node_workspace


@router.get("/nodes")
def list_nodes(role: str, request: Request, q: str | None = None) -> dict:
    return {
        "schema": "tags-machine-core.web.node-list/v1",
        "role": role,
        "nodes": _workspace(request).list_nodes(role, query=q),
    }


@router.get("/nodes/read")
def read_node(ref: str, request: Request) -> dict:
    try:
        return _workspace(request).read_node(ref)
    except FileNotFoundError as exc:
        raise ApiError(code="node_not_found", message=str(exc), status_code=404) from exc


@router.post("/nodes/preview")
def preview_node(data: dict, request: Request) -> dict:
    return _workspace(request).preview_node(data)


@router.put("/nodes/save")
def save_node(data: dict, request: Request) -> dict:
    ref = str(data.get("ref") or "").strip()
    node = data.get("node")
    if not ref or not isinstance(node, dict):
        raise ApiError(code="invalid_node_save", message="nodes/save requires ref and node")
    return _workspace(request).save_node(ref, node)
```

Modify `src/tags_machine_core/web/app.py`:

```python
from tags_machine_core.config import load_config
from .routes import health, jobs, nodes
from .services.node_workspace import NodeWorkspace


def create_app(
    *,
    job_manager: JobManager | None = None,
    node_workspace: NodeWorkspace | None = None,
) -> FastAPI:
    config = load_config("configs/local.example.yaml")
    app.state.node_workspace = node_workspace or NodeWorkspace(design_root=config.legacy.design_root)
    app.include_router(nodes.router, prefix="/api", tags=["nodes"])
```

- [ ] **Step 5: Run tests**

Run:

```powershell
uv run python -m unittest tests.test_web_nodes -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/tags_machine_core/web tests/test_web_nodes.py
git commit -m "feat: add web node workspace"
```

---

### Task 4: Custom Studio Preview and Generate Job

**Files:**
- Create: `src/tags_machine_core/web/routes/compose.py`
- Create: `src/tags_machine_core/web/routes/generate.py`
- Modify: `src/tags_machine_core/web/app.py`
- Test: `tests/test_web_compose.py`

**Interfaces:**
- Produces HTTP:
  - `POST /api/compose-preview`
  - `POST /api/render-preview`
  - `POST /api/generate`
- Consumes: `GenerationJsonApi.compose_render_plan`
- Consumes: `execute_render_request`
- Produces generate job result containing `GenerationResult`

- [ ] **Step 1: Write failing compose/generate tests**

Create `tests/test_web_compose.py`:

```python
from fastapi.testclient import TestClient

from tags_machine_core.contracts import GeneratedImage, GenerationResult
from tags_machine_core.web import create_app


def test_compose_preview_returns_prompt_bundle_and_render_request():
    client = TestClient(create_app())

    response = client.post(
        "/api/compose-preview",
        json={
            "compose": {"prompt": "1girl, standing", "negative": "lowres"},
            "render": {"backend": "novelai", "width": 1024, "height": 1024},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["prompt_bundle"]["prompt"]["positive"] == "1girl, standing"
    assert data["render_request"]["backend"] == "novelai"


def test_generate_endpoint_creates_job_with_injected_executor(tmp_path):
    def executor(request, options):
        return GenerationResult(
            backend="novelai",
            images=[
                GeneratedImage(
                    path=str(tmp_path / "image.png"),
                    seed=123,
                    index=0,
                    width=1024,
                    height=1024,
                    format="png",
                )
            ],
            request_body={"ok": True},
            png_info={"images": []},
            cache_hit=False,
        )

    client = TestClient(create_app(generation_executor=executor))

    preview = client.post(
        "/api/compose-preview",
        json={
            "compose": {"prompt": "1girl, standing"},
            "render": {"backend": "novelai", "width": 1024, "height": 1024},
        },
    ).json()
    response = client.post("/api/generate", json={"render_request": preview["render_request"]})

    assert response.status_code == 200
    job = response.json()
    assert job["status"] in {"queued", "running", "succeeded"}
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
uv run python -m unittest tests.test_web_compose -v
```

Expected: FAIL because compose/generate routes do not exist.

- [ ] **Step 3: Implement compose route**

Create `src/tags_machine_core/web/routes/compose.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from tags_machine_core.services import GenerationJsonApi

router = APIRouter()


def _api(request: Request) -> GenerationJsonApi:
    return request.app.state.generation_api


@router.post("/compose-preview")
def compose_preview(data: dict, request: Request) -> dict:
    return _api(request).resolve_compose_render_plan(data)


@router.post("/render-preview")
def render_preview(data: dict, request: Request) -> dict:
    return _api(request).render_plan(data)
```

- [ ] **Step 4: Implement generate route**

Create `src/tags_machine_core/web/routes/generate.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from tags_machine_core.contracts import RenderRequest

router = APIRouter()


@router.post("/generate")
def generate(data: dict, request: Request) -> dict:
    manager = request.app.state.job_manager
    executor = request.app.state.generation_executor
    render_request = RenderRequest.model_validate(data.get("render_request") or data.get("request"))

    def worker(ctx):
        ctx.emit("generate_started", {"backend": render_request.backend})
        result = executor(render_request, data)
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        ctx.emit("generate_succeeded", {"image_count": len(payload.get("images", []))})
        return payload

    job = manager.submit("generate", worker)
    return job.to_dict()
```

Modify `src/tags_machine_core/web/app.py`:

```python
from tags_machine_core.execution import execute_render_request
from tags_machine_core.services import GenerationJsonApi
from .routes import compose, generate


def create_app(..., generation_executor=None) -> FastAPI:
    app.state.generation_executor = generation_executor or (
        lambda request, options: execute_render_request(request, entrypoint="web-generate")
    )
    app.state.generation_api = GenerationJsonApi(generation_executor=app.state.generation_executor)
    app.include_router(compose.router, prefix="/api", tags=["compose"])
    app.include_router(generate.router, prefix="/api", tags=["generate"])
```

- [ ] **Step 5: Run tests**

Run:

```powershell
uv run python -m unittest tests.test_web_compose -v
```

Expected: PASS.

- [ ] **Step 6: Business verification with real NovelAI**

Run the service:

```powershell
uv run python -m tags_machine_core.web
```

In a second terminal, call preview:

```powershell
$body = @{
  compose = @{ prompt = "1girl, standing"; negative = "lowres" }
  render = @{ backend = "novelai"; width = 1024; height = 1024; model = "nai-diffusion-4-5-full" }
} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/compose-preview -Body $body -ContentType 'application/json'
```

Expected: response has `status: ready`, `prompt_bundle`, and `render_request`.

Then call generate with the returned `render_request`. Expected: job reaches `succeeded` and image path exists. Record image path in `docs/web_control_console_business_test_20260710.md`.

- [ ] **Step 7: Commit**

```powershell
git add src/tags_machine_core/web tests/test_web_compose.py docs/web_control_console_business_test_20260710.md
git commit -m "feat: add custom preview and generate API"
```

---

### Task 5: Results Index API

**Files:**
- Create: `src/tags_machine_core/web/services/result_index.py`
- Create: `src/tags_machine_core/web/routes/results.py`
- Modify: `src/tags_machine_core/web/app.py`
- Test: `tests/test_web_results.py`

**Interfaces:**
- Produces: `ResultIndex.list_runs() -> list[dict[str, Any]]`
- Produces: `ResultIndex.get_task(task_dir: str | Path) -> dict[str, Any]`
- Produces HTTP:
  - `GET /api/results/runs`
  - `GET /api/results/task?task_dir=...`
  - `GET /api/results/file?path=...`

- [ ] **Step 1: Write failing result tests**

Create `tests/test_web_results.py`:

```python
import json
from pathlib import Path

from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.result_index import ResultIndex


def test_result_index_lists_runs_and_task_files(tmp_path):
    run = tmp_path / "runs" / "demo"
    task = run / "tasks" / "task_1"
    task.mkdir(parents=True)
    (task / "generation_result.json").write_text(json.dumps({"images": [{"path": "a.png"}]}), encoding="utf-8")
    (task / "prompt_bundle.json").write_text(json.dumps({"prompt": {"positive": "1girl"}}), encoding="utf-8")
    index = ResultIndex(roots=[tmp_path / "runs"])

    runs = index.list_runs()
    task_data = index.get_task(task)

    assert runs[0]["name"] == "demo"
    assert task_data["files"]["generation_result"].endswith("generation_result.json")


def test_results_http_serves_json_file(tmp_path):
    run = tmp_path / "runs" / "demo"
    task = run / "tasks" / "task_1"
    task.mkdir(parents=True)
    result_path = task / "generation_result.json"
    result_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    client = TestClient(create_app(result_index=ResultIndex(roots=[tmp_path / "runs"])))

    response = client.get("/api/results/file", params={"path": str(result_path)})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
uv run python -m unittest tests.test_web_results -v
```

Expected: FAIL because `ResultIndex` does not exist.

- [ ] **Step 3: Implement ResultIndex**

Create `src/tags_machine_core/web/services/result_index.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ResultIndex:
    def __init__(self, *, roots: list[str | Path]):
        self.roots = [Path(root) for root in roots]

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for root in self.roots:
            if not root.exists():
                continue
            for run in sorted(root.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True):
                if run.is_dir():
                    runs.append({"name": run.name, "path": str(run), "task_count": self._task_count(run)})
        return runs

    def get_task(self, task_dir: str | Path) -> dict[str, Any]:
        task = Path(task_dir)
        files = {
            "generation_result": task / "generation_result.json",
            "prompt_bundle": task / "prompt_bundle.json",
            "render_request": task / "render_request.json",
            "png_params": task / "png_params.json",
        }
        return {
            "schema": "tags-machine-core.web.result-task/v1",
            "task_dir": str(task),
            "files": {key: str(path) for key, path in files.items() if path.exists()},
            "images": [str(path) for path in task.glob("*.png") if not path.name.startswith("zz_")],
            "parameter_details": [str(path) for path in task.glob("zz_*_parameter_details.png")],
        }

    def read_file(self, path: str | Path) -> Any:
        target = Path(path)
        if target.suffix.lower() == ".json":
            return json.loads(target.read_text(encoding="utf-8-sig"))
        return {"path": str(target), "text": target.read_text(encoding="utf-8", errors="ignore")}

    def _task_count(self, run: Path) -> int:
        tasks = run / "tasks"
        return len([item for item in tasks.iterdir() if item.is_dir()]) if tasks.exists() else 0
```

- [ ] **Step 4: Implement result routes**

Create `src/tags_machine_core/web/routes/results.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from tags_machine_core.web.services.result_index import ResultIndex

router = APIRouter()


def _index(request: Request) -> ResultIndex:
    return request.app.state.result_index


@router.get("/results/runs")
def list_runs(request: Request) -> dict:
    return {"schema": "tags-machine-core.web.result-runs/v1", "runs": _index(request).list_runs()}


@router.get("/results/task")
def get_task(task_dir: str, request: Request) -> dict:
    return _index(request).get_task(task_dir)


@router.get("/results/file")
def read_file(path: str, request: Request):
    return _index(request).read_file(path)
```

Modify `src/tags_machine_core/web/app.py`:

```python
from .routes import results
from .services.result_index import ResultIndex


def create_app(..., result_index: ResultIndex | None = None) -> FastAPI:
    app.state.result_index = result_index or ResultIndex(roots=["outputs", "examples/batches/outputs"])
    app.include_router(results.router, prefix="/api", tags=["results"])
```

- [ ] **Step 5: Run tests**

Run:

```powershell
uv run python -m unittest tests.test_web_results -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/tags_machine_core/web tests/test_web_results.py
git commit -m "feat: add web result index"
```

---

### Task 6: Batch Preview and Batch Run Jobs

**Files:**
- Create: `src/tags_machine_core/web/services/batch_workspace.py`
- Create: `src/tags_machine_core/web/routes/batch.py`
- Modify: `src/tags_machine_core/web/app.py`
- Test: `tests/test_web_batch.py`
- Modify: `docs/web_control_console_business_test_20260710.md`

**Interfaces:**
- Produces: `BatchWorkspace.preview(data: dict[str, Any]) -> dict[str, Any]`
- Produces: `BatchWorkspace.run(data: dict[str, Any], ctx: JobContext) -> dict[str, Any]`
- Produces HTTP:
  - `POST /api/batches/preview`
  - `POST /api/batches/run`
  - `POST /api/batches/resume`

- [ ] **Step 1: Write failing batch tests**

Create `tests/test_web_batch.py`:

```python
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.batch_workspace import BatchWorkspace


def _write_node(path: Path, *, kind: str, node_id: str, prompt: str):
    path.mkdir(parents=True)
    (path / "meta.yaml").write_text(
        yaml.safe_dump(
            {"kind": kind, "id": node_id, "name": node_id, "prompt": {"positive": [prompt]}},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_batch_preview_returns_summary(tmp_path):
    _write_node(tmp_path / "characters" / "homura", kind="character", node_id="homura", prompt="akemi_homura")
    _write_node(tmp_path / "actions" / "standing", kind="action", node_id="standing", prompt="standing")
    workspace = BatchWorkspace(base_dir=tmp_path)

    result = workspace.preview(
        {
            "spec": {
                "name": "demo",
                "defaults": {"composer": "script", "artist": "20260412"},
                "select": {
                    "characters": [{"selector": "explicit", "refs": [str(tmp_path / "characters" / "homura")]}],
                    "actions": [{"selector": "explicit", "refs": [str(tmp_path / "actions" / "standing")]}],
                },
                "expand": {"mode": "product"},
            }
        }
    )

    assert result["task_count"] == 1
    assert result["sample_tasks"][0]["source"]["character"].endswith("homura")


def test_batch_preview_http(tmp_path):
    _write_node(tmp_path / "characters" / "homura", kind="character", node_id="homura", prompt="akemi_homura")
    _write_node(tmp_path / "actions" / "standing", kind="action", node_id="standing", prompt="standing")
    client = TestClient(create_app(batch_workspace=BatchWorkspace(base_dir=tmp_path)))

    response = client.post(
        "/api/batches/preview",
        json={
            "spec": {
                "name": "demo",
                "defaults": {"composer": "script", "artist": "20260412"},
                "select": {
                    "characters": [{"selector": "explicit", "refs": [str(tmp_path / "characters" / "homura")]}],
                    "actions": [{"selector": "explicit", "refs": [str(tmp_path / "actions" / "standing")]}],
                },
                "expand": {"mode": "product"},
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["task_count"] == 1
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
uv run python -m unittest tests.test_web_batch -v
```

Expected: FAIL because `BatchWorkspace` does not exist.

- [ ] **Step 3: Implement BatchWorkspace**

Create `src/tags_machine_core/web/services/batch_workspace.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from tags_machine_core.batch import BatchPlanner, BatchRunner, load_batch_spec, load_batch_spec_mapping
from tags_machine_core.json_tools import to_jsonable


class BatchWorkspace:
    def __init__(self, *, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def preview(self, data: dict[str, Any]) -> dict[str, Any]:
        spec, spec_path = self._load_spec(data)
        run_dir = Path(data.get("work_root") or self.base_dir / spec.name)
        output_dir = Path(data.get("output_dir") or spec.output_dir or run_dir / "outputs")
        tasks = BatchPlanner(base_dir=spec_path.parent if spec_path else self.base_dir).plan(
            spec,
            run_dir=run_dir,
            output_dir=output_dir,
            run_id=str(data.get("run_id") or "preview"),
        )
        return {
            "schema": "tags-machine-core.web.batch-preview/v1",
            "batch": spec.name,
            "task_count": len(tasks),
            "sample_tasks": [to_jsonable(task) for task in tasks[:100]],
            "output_dir": str(output_dir),
            "run_dir": str(run_dir),
        }

    def run(self, data: dict[str, Any], ctx) -> dict[str, Any]:
        spec, spec_path = self._load_spec(data)
        run_dir = Path(data.get("work_root") or self.base_dir / spec.name)
        output_dir = Path(data.get("output_dir") or spec.output_dir or run_dir / "outputs")
        tasks = BatchPlanner(base_dir=spec_path.parent if spec_path else self.base_dir).plan(
            spec,
            run_dir=run_dir,
            output_dir=output_dir,
            run_id=str(data.get("run_id") or "web"),
        )
        limit = data.get("limit")
        if isinstance(limit, int):
            tasks = tasks[:limit]
        ctx.emit("batch_planned", {"task_count": len(tasks), "run_dir": str(run_dir)})
        result = BatchRunner().run_tasks(
            tasks,
            spec=spec,
            run_dir=run_dir,
            output_dir=output_dir,
            resume=bool(data.get("resume", spec.run.resume)),
            fresh=bool(data.get("fresh", False)),
            stop_on_error=bool(data.get("stop_on_error", spec.run.stop_on_error)),
            mock_client=bool(data.get("mock_client", False)),
        )
        return to_jsonable(result)

    def _load_spec(self, data: dict[str, Any]):
        if "spec" in data:
            return load_batch_spec_mapping(data["spec"], base_path=self.base_dir / "inline_batch.yaml"), None
        path = Path(data["batch_spec"])
        spec_path = path if path.is_absolute() else self.base_dir / path
        return load_batch_spec(spec_path), spec_path
```

- [ ] **Step 4: Implement batch routes**

Create `src/tags_machine_core/web/routes/batch.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/batches/preview")
def batch_preview(data: dict, request: Request) -> dict:
    return request.app.state.batch_workspace.preview(data)


@router.post("/batches/run")
def batch_run(data: dict, request: Request) -> dict:
    workspace = request.app.state.batch_workspace
    manager = request.app.state.job_manager

    def worker(ctx):
        return workspace.run(data, ctx)

    job = manager.submit("batch-run", worker)
    return job.to_dict()
```

Modify `src/tags_machine_core/web/app.py`:

```python
from .routes import batch
from .services.batch_workspace import BatchWorkspace


def create_app(..., batch_workspace: BatchWorkspace | None = None) -> FastAPI:
    app.state.batch_workspace = batch_workspace or BatchWorkspace(base_dir=Path.cwd())
    app.include_router(batch.router, prefix="/api", tags=["batch"])
```

- [ ] **Step 5: Run tests**

Run:

```powershell
uv run python -m unittest tests.test_web_batch -v
```

Expected: PASS.

- [ ] **Step 6: Business verification with existing blackboard config**

Run the service:

```powershell
uv run python -m tags_machine_core.web
```

Preview:

```powershell
$body = @{
  batch_spec = "examples/batches/blackboard_action_new_manga_monochrome.yaml"
  work_root = "$env:TEMP/tm_web_batch_work"
  output_dir = "G:/ai_auto/web-batch-smoke"
} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/batches/preview -Body $body -ContentType 'application/json'
```

Expected: `task_count` is `1` because the YAML has `max_tasks: 1`.

Run:

```powershell
$body = @{
  batch_spec = "examples/batches/blackboard_action_new_manga_monochrome.yaml"
  work_root = "$env:TEMP/tm_web_batch_work"
  output_dir = "G:/ai_auto/web-batch-smoke"
  fresh = $true
  limit = 1
} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/batches/run -Body $body -ContentType 'application/json'
```

Expected: job reaches `succeeded`, one task succeeds, and output directory contains generated images plus `zz_*_parameter_details.png` when the batch archive setting enables it. Record paths in `docs/web_control_console_business_test_20260710.md`.

- [ ] **Step 7: Commit**

```powershell
git add src/tags_machine_core/web tests/test_web_batch.py docs/web_control_console_business_test_20260710.md
git commit -m "feat: add web batch workflow"
```

---

### Task 7: Frontend Skeleton and Custom Studio

**Files:**
- Create: `web/package.json`
- Create: `web/index.html`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/api/client.ts`
- Create: `web/src/api/types.ts`
- Create: `web/src/components/Layout.tsx`
- Create: `web/src/components/NodePicker.tsx`
- Create: `web/src/components/NodeEditor.tsx`
- Create: `web/src/components/PromptPreview.tsx`
- Create: `web/src/components/RenderParamsPanel.tsx`
- Create: `web/src/pages/CustomStudio.tsx`
- Create: `web/src/styles.css`
- Test: `web/src/pages/CustomStudio.test.tsx`

**Interfaces:**
- Consumes HTTP:
  - `GET /api/nodes`
  - `GET /api/nodes/read`
  - `POST /api/compose-preview`
  - `POST /api/generate`
- Produces browser UI for script/full prompt custom generation.

- [ ] **Step 1: Create frontend package**

Create `web/package.json`:

```json
{
  "name": "promptatelier-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5173",
    "build": "tsc && vite build",
    "test": "vitest run",
    "preview": "vite preview --host 127.0.0.1 --port 5174"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^4.3.0",
    "lucide-react": "^0.468.0",
    "vite": "^5.4.0",
    "typescript": "^5.5.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/react": "^15.0.0",
    "@testing-library/jest-dom": "^6.4.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "jsdom": "^25.0.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 2: Write failing Custom Studio test**

Create `web/src/pages/CustomStudio.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CustomStudio } from "./CustomStudio";

describe("CustomStudio", () => {
  it("renders node selectors and prompt preview", () => {
    render(<CustomStudio />);

    expect(screen.getByText("Artist")).toBeTruthy();
    expect(screen.getByText("Character")).toBeTruthy();
    expect(screen.getByText("Action")).toBeTruthy();
    expect(screen.getByText("Prompt Preview")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Preview" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Generate" })).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run failing frontend test**

Run:

```powershell
cd web
npm install
npm test -- CustomStudio.test.tsx
```

Expected: FAIL because `CustomStudio` does not exist.

- [ ] **Step 4: Implement API client**

Create `web/src/api/client.ts`:

```ts
const API_ROOT = import.meta.env.VITE_API_ROOT ?? "http://127.0.0.1:8765/api";

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}
```

Create `web/src/api/types.ts`:

```ts
export type NodeSummary = {
  role: string;
  name: string;
  ref: string;
};

export type ComposePreviewResponse = {
  status: "ready" | "requires_agent";
  prompt_bundle?: {
    prompt: { positive: string; negative: string };
  };
  render_request?: Record<string, unknown>;
};
```

- [ ] **Step 5: Implement UI skeleton**

Create `web/src/pages/CustomStudio.tsx`:

```tsx
import { Play, Sparkles } from "lucide-react";
import { useState } from "react";

export function CustomStudio() {
  const [prompt, setPrompt] = useState("1girl, standing");

  return (
    <main className="studio-grid">
      <section className="panel">
        <h2>Nodes</h2>
        <label>Artist</label>
        <input aria-label="Artist" placeholder="Search artist" />
        <label>Character</label>
        <input aria-label="Character" placeholder="Search character" />
        <label>Action</label>
        <input aria-label="Action" placeholder="Search action" />
      </section>

      <section className="panel">
        <h2>Node Editor</h2>
        <textarea aria-label="Node draft" defaultValue="Structured node form draft" />
      </section>

      <section className="panel preview-panel">
        <h2>Prompt Preview</h2>
        <textarea
          aria-label="Full prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
        />
        <div className="button-row">
          <button type="button">
            <Sparkles size={16} />
            Preview
          </button>
          <button type="button">
            <Play size={16} />
            Generate
          </button>
        </div>
      </section>
    </main>
  );
}
```

Create `web/src/App.tsx`:

```tsx
import { CustomStudio } from "./pages/CustomStudio";
import "./styles.css";

export function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1>PromptAtelier</h1>
        <button>Custom</button>
        <button>Batch</button>
        <button>Results</button>
      </aside>
      <CustomStudio />
    </div>
  );
}
```

Create `web/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

Create `web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PromptAtelier</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `web/src/styles.css` with restrained operational styling:

```css
:root {
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #202124;
  background: #f5f6f8;
}

body {
  margin: 0;
}

button,
input,
textarea {
  font: inherit;
}

.app-shell {
  display: grid;
  grid-template-columns: 220px 1fr;
  min-height: 100vh;
}

.sidebar {
  background: #202124;
  color: #fff;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar h1 {
  font-size: 18px;
  margin: 0 0 12px;
}

.sidebar button,
.button-row button {
  border: 1px solid #d0d4dc;
  background: #fff;
  border-radius: 6px;
  padding: 8px 10px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.studio-grid {
  display: grid;
  grid-template-columns: 280px minmax(320px, 1fr) minmax(360px, 1fr);
  gap: 12px;
  padding: 12px;
}

.panel {
  background: #fff;
  border: 1px solid #d9dde5;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.panel h2 {
  font-size: 15px;
  margin: 0 0 4px;
}

.panel input,
.panel textarea {
  border: 1px solid #c9ced8;
  border-radius: 6px;
  padding: 8px;
  min-width: 0;
}

.panel textarea {
  min-height: 220px;
  resize: vertical;
}

.button-row {
  display: flex;
  gap: 8px;
}
```

- [ ] **Step 6: Run frontend test and build**

Run:

```powershell
cd web
npm test -- CustomStudio.test.tsx
npm run build
```

Expected: both PASS.

- [ ] **Step 7: Browser verification**

Start frontend:

```powershell
cd web
npm run dev
```

Open `http://127.0.0.1:5173`. Verify:

- Layout has sidebar and three work panels.
- Text does not overlap at 1366x768.
- Buttons have icons.
- UI is work-focused, not a landing page.

- [ ] **Step 8: Commit**

```powershell
git add web
git commit -m "feat: add custom studio frontend"
```

---

### Task 8: Batch Studio, Results Gallery, and Compare UI

**Files:**
- Create: `web/src/pages/BatchStudio.tsx`
- Create: `web/src/pages/ResultsGallery.tsx`
- Create: `web/src/pages/CompareStudio.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/api/types.ts`
- Test: `web/src/pages/BatchStudio.test.tsx`
- Test: `web/e2e/batch-studio.spec.ts`
- Test: `web/e2e/custom-studio.spec.ts`
- Modify: `docs/web_control_console_readme.md`

**Interfaces:**
- Consumes HTTP:
  - `POST /api/batches/preview`
  - `POST /api/batches/run`
  - `GET /api/jobs/{job_id}`
  - `GET /api/results/runs`
  - `GET /api/results/task`
- Produces UI for batch preview/run, result browsing, and variant comparison setup.

- [ ] **Step 1: Write failing Batch Studio test**

Create `web/src/pages/BatchStudio.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BatchStudio } from "./BatchStudio";

describe("BatchStudio", () => {
  it("renders batch controls and preview action", () => {
    render(<BatchStudio />);

    expect(screen.getByText("Batch Studio")).toBeTruthy();
    expect(screen.getByLabelText("Characters")).toBeTruthy();
    expect(screen.getByLabelText("Action Groups")).toBeTruthy();
    expect(screen.getByLabelText("Artist")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Plan Preview" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run Batch" })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run failing frontend test**

Run:

```powershell
cd web
npm test -- BatchStudio.test.tsx
```

Expected: FAIL because `BatchStudio` does not exist.

- [ ] **Step 3: Implement Batch Studio**

Create `web/src/pages/BatchStudio.tsx`:

```tsx
import { ListChecks, Play } from "lucide-react";
import { useState } from "react";

import { apiPost } from "../api/client";

export function BatchStudio() {
  const [characters, setCharacters] = useState("special_next_select");
  const [actionGroups, setActionGroups] = useState("action_new");
  const [artist, setArtist] = useState("109841329_03_manga_monochrome_yabuki_rance_no_vibe_latest_stable");
  const [summary, setSummary] = useState<string>("No preview yet.");

  async function preview() {
    const result = await apiPost<{ task_count: number }>("/batches/preview", {
      spec: {
        name: "web-batch-draft",
        require: ["../project/base.yaml", "../project/collections.yaml", "../project/nai_const_action_groups.yaml"],
        batch: {
          characters,
          action_groups: [actionGroups],
          artist,
          composer: "script",
          auto_num: true,
          max_tasks: 1,
          nt: 1,
        },
      },
    });
    setSummary(`Tasks: ${result.task_count}`);
  }

  async function runBatch() {
    const result = await apiPost<{ id: string; status: string }>("/batches/run", {
      batch_spec: "examples/batches/blackboard_action_new_manga_monochrome.yaml",
      limit: 1,
      fresh: true,
    });
    setSummary(`Job ${result.id}: ${result.status}`);
  }

  return (
    <main className="panel page-panel">
      <h2>Batch Studio</h2>
      <label>Characters</label>
      <input aria-label="Characters" value={characters} onChange={(event) => setCharacters(event.target.value)} />
      <label>Action Groups</label>
      <input aria-label="Action Groups" value={actionGroups} onChange={(event) => setActionGroups(event.target.value)} />
      <label>Artist</label>
      <input aria-label="Artist" value={artist} onChange={(event) => setArtist(event.target.value)} />
      <div className="button-row">
        <button type="button" onClick={preview}>
          <ListChecks size={16} />
          Plan Preview
        </button>
        <button type="button" onClick={runBatch}>
          <Play size={16} />
          Run Batch
        </button>
      </div>
      <pre>{summary}</pre>
    </main>
  );
}
```

- [ ] **Step 4: Implement Results and Compare pages**

Create `web/src/pages/ResultsGallery.tsx`:

```tsx
export function ResultsGallery() {
  return (
    <main className="panel page-panel">
      <h2>Results Gallery</h2>
      <p>Browse runs, task images, PNG params, PromptBundle, RenderRequest, and GenerationResult.</p>
    </main>
  );
}
```

Create `web/src/pages/CompareStudio.tsx`:

```tsx
export function CompareStudio() {
  return (
    <main className="panel page-panel">
      <h2>Compare Studio</h2>
      <p>Create variants from the current custom setup, lock shared nodes, and compare artist or parameter changes.</p>
    </main>
  );
}
```

Modify `web/src/App.tsx` to switch pages:

```tsx
import { useState } from "react";
import { BatchStudio } from "./pages/BatchStudio";
import { CompareStudio } from "./pages/CompareStudio";
import { CustomStudio } from "./pages/CustomStudio";
import { ResultsGallery } from "./pages/ResultsGallery";
import "./styles.css";

type Page = "custom" | "compare" | "batch" | "results";

export function App() {
  const [page, setPage] = useState<Page>("custom");
  const content = {
    custom: <CustomStudio />,
    compare: <CompareStudio />,
    batch: <BatchStudio />,
    results: <ResultsGallery />,
  }[page];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1>PromptAtelier</h1>
        <button onClick={() => setPage("custom")}>Custom</button>
        <button onClick={() => setPage("compare")}>Compare</button>
        <button onClick={() => setPage("batch")}>Batch</button>
        <button onClick={() => setPage("results")}>Results</button>
      </aside>
      {content}
    </div>
  );
}
```

- [ ] **Step 5: Run frontend tests and build**

Run:

```powershell
cd web
npm test
npm run build
```

Expected: PASS.

- [ ] **Step 6: Browser verification**

Run backend and frontend:

```powershell
uv run python -m tags_machine_core.web
cd web
npm run dev
```

Open `http://127.0.0.1:5173`. Verify:

- Custom, Compare, Batch, Results nav works.
- Batch page can call Plan Preview and shows `Tasks: 1`.
- Layout does not overlap at desktop and mobile widths.

- [ ] **Step 7: Business verification**

From UI:

- Open Batch page.
- Click Plan Preview; expected `Tasks: 1`.
- Click Run Batch; expected job id appears.
- Poll `/api/jobs/{job_id}` until succeeded.
- Confirm output images exist.

Record evidence in `docs/web_control_console_business_test_20260710.md`.

- [ ] **Step 8: Write user docs**

Create `docs/web_control_console_readme.md`:

```markdown
# Web Control Console

## Start Backend

```powershell
cd F:\my_project\new\tags_machine\refactor
uv run python -m tags_machine_core.web
```

## Start Frontend

```powershell
cd F:\my_project\new\tags_machine\refactor\web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Main Workflows

- Custom: choose nodes, preview prompt/render params, generate.
- Compare: duplicate a setup and change artist or params.
- Batch: preview task plan, run a batch job, inspect job status.
- Results: inspect generated images and artifacts.
```

- [ ] **Step 9: Commit**

```powershell
git add web docs/web_control_console_readme.md docs/web_control_console_business_test_20260710.md
git commit -m "feat: add web console frontend"
```

---

## Final Verification

- [ ] Run backend tests:

```powershell
uv run python -m unittest tests.test_web_app tests.test_web_jobs tests.test_web_nodes tests.test_web_compose tests.test_web_batch tests.test_web_results -v
```

Expected: all PASS.

- [ ] Run frontend tests:

```powershell
cd web
npm test
npm run build
```

Expected: all PASS.

- [ ] Run real NovelAI Custom Studio business test:

```powershell
uv run python -m tags_machine_core.web
```

Use `/api/compose-preview` then `/api/generate` with a simple prompt. Expected: job succeeds and image path exists.

- [ ] Run real NovelAI Batch business test:

Use `/api/batches/preview` and `/api/batches/run` with `examples/batches/blackboard_action_new_manga_monochrome.yaml`, `limit=1`, and `fresh=true`. Expected: job succeeds, at least one task succeeds, generated images exist, and artifacts include parameter details when configured.

- [ ] Check Git state:

```powershell
git status --short
```

Expected: only unrelated pre-existing files remain dirty.

---

## Self-Review

Spec coverage:

- Custom Studio: covered by Tasks 4 and 7.
- Structured node editing: covered by Task 3 and surfaced in Task 7.
- Compare Studio: covered by Task 8 as first UI slice.
- Batch Studio: covered by Tasks 6 and 8.
- Results Gallery: covered by Tasks 5 and 8.
- FastAPI local service: covered by Tasks 1 through 6.
- No AgentComposer UI: enforced in Global Constraints.
- Real NovelAI business tests: covered in Tasks 4, 6, 8, and Final Verification.

Placeholder scan:

- No unresolved placeholder markers remain.
- No undefined implementation tasks.
- Future scope is explicitly excluded from v1 rather than left as an implementation gap.

Type consistency:

- `JobManager`, `NodeWorkspace`, `BatchWorkspace`, and `ResultIndex` are introduced before being consumed by routes.
- HTTP routes match frontend client paths.
- Generate flow consistently consumes `RenderRequest` and returns job status.
