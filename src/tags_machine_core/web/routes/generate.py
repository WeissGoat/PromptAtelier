from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from tags_machine_core.web.errors import ApiError
from tags_machine_core.web.routes.compose import _validate_prompt_policy_override
from tags_machine_core.web.services.generate_batch import (
    GENERATE_BATCH_JOB,
    attach_random_selections,
    run_generate,
    run_generate_batch,
    validate_generate_batch,
)


router = APIRouter()


@router.post("/generate")
def generate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    manager = request.app.state.job_manager
    api = request.app.state.generation_api
    try:
        prepared = attach_random_selections(payload)
    except ValueError as exc:
        raise ApiError(
            code="invalid_random_selections",
            message=str(exc),
            status_code=400,
        ) from exc

    def worker(ctx):
        return run_generate(api, prepared, ctx.emit)

    try:
        job = manager.submit("generate", worker)
    except ValueError as exc:
        raise ApiError(
            code="generate_failed",
            message=str(exc),
            status_code=400,
        ) from exc
    return job.to_dict()


@router.post("/generate/batch")
def generate_batch(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """后台批量出图：浏览器把逐项的 compose 请求一次交给后端，关掉网页也会跑完。"""
    manager = request.app.state.job_manager
    api = request.app.state.generation_api
    try:
        batch = validate_generate_batch(payload)
        for item in batch["items"]:
            _validate_prompt_policy_override(item["compose_request"])
    except ValueError as exc:
        raise ApiError(
            code="invalid_generate_batch",
            message=str(exc),
            status_code=400,
        ) from exc

    def worker(ctx):
        return run_generate_batch(api, batch, ctx)

    return manager.submit(GENERATE_BATCH_JOB, worker, request=batch).to_dict()


@router.post("/generate/batch/{job_id}/resume")
def resume_generate_batch(job_id: str, request: Request) -> dict[str, Any]:
    """被停止、失败或后端重启打断的批量任务：在原任务里接着跑没成功的项，图片还写回原目录。"""
    manager = request.app.state.job_manager
    api = request.app.state.generation_api
    try:
        job = manager.get(job_id)
        batch = manager.request_of(job_id)
    except KeyError as exc:
        raise ApiError(code="job_not_found", message=f"Job not found: {job_id}", status_code=404) from exc
    if job.name != GENERATE_BATCH_JOB or not isinstance(batch, dict):
        raise ApiError(
            code="job_not_resumable",
            message="这个任务没有保存原始请求，无法继续。",
            status_code=400,
        )
    previous = job.result if isinstance(job.result, dict) else None
    items = (previous or {}).get("items") or []
    if items and all(isinstance(item, dict) and item.get("status") == "succeeded" for item in items):
        raise ApiError(code="job_not_resumable", message="这个任务的每一项都已经成功。", status_code=409)

    def worker(ctx):
        return run_generate_batch(api, batch, ctx, previous=previous)

    try:
        return manager.resume(job_id, worker).to_dict()
    except ValueError as exc:
        raise ApiError(code="job_not_resumable", message=str(exc), status_code=409) from exc
