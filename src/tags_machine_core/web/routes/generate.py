from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from tags_machine_core.web.errors import ApiError


router = APIRouter()


@router.post("/generate")
def generate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    manager = request.app.state.job_manager
    api = request.app.state.generation_api

    def worker(ctx):
        ctx.emit("generation_started", {})
        result = api.generate(payload)
        ctx.emit(
            "generation_finished",
            {"image_count": len(result.get("images") or [])},
        )
        return result

    try:
        job = manager.submit("generate", worker)
    except ValueError as exc:
        raise ApiError(
            code="generate_failed",
            message=str(exc),
            status_code=400,
        ) from exc
    return job.to_dict()
