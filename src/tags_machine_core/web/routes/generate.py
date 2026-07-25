from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from tags_machine_core.web.errors import ApiError


router = APIRouter()


@router.post("/generate")
def generate(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    manager = request.app.state.job_manager
    api = request.app.state.generation_api
    prepared = _attach_random_selections(payload)

    def worker(ctx):
        ctx.emit("generation_started", {})
        result = api.generate(prepared)
        if prepared.get("random_selections"):
            result["random_selections"] = prepared["random_selections"]
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


def _attach_random_selections(payload: dict[str, Any]) -> dict[str, Any]:
    selections = payload.get("random_selections")
    if selections is None:
        return payload
    if not isinstance(selections, list) or not all(isinstance(item, dict) for item in selections):
        raise ApiError(
            code="invalid_random_selections",
            message="random_selections must be a list of objects",
            status_code=400,
        )
    request_data = payload.get("render_request") or payload.get("request")
    if not isinstance(request_data, dict):
        raise ApiError(
            code="invalid_random_selections",
            message="random selections require render_request",
            status_code=400,
        )
    render_request = dict(request_data)
    meta = dict(render_request.get("meta") or {})
    meta["random_nodes"] = selections
    render_request["meta"] = meta
    result = dict(payload)
    result["render_request"] = render_request
    result["random_selections"] = selections
    return result
