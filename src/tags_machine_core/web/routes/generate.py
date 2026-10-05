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

    return manager.submit(GENERATE_BATCH_JOB, worker).to_dict()
