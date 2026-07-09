from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from tags_machine_core.web.errors import ApiError


router = APIRouter()


@router.post("/batches/preview")
def batch_preview(data: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        return request.app.state.batch_workspace.preview(data)
    except (FileNotFoundError, ValueError) as exc:
        raise ApiError(
            code="batch_preview_failed",
            message=str(exc),
            status_code=400,
        ) from exc


@router.post("/batches/run")
def batch_run(data: dict[str, Any], request: Request) -> dict[str, Any]:
    workspace = request.app.state.batch_workspace
    manager = request.app.state.job_manager

    def worker(ctx):
        return workspace.run(data, ctx)

    return manager.submit("batch-run", worker).to_dict()


@router.post("/batches/resume")
def batch_resume(data: dict[str, Any], request: Request) -> dict[str, Any]:
    workspace = request.app.state.batch_workspace
    manager = request.app.state.job_manager

    def worker(ctx):
        return workspace.resume(data, ctx)

    return manager.submit("batch-resume", worker).to_dict()
