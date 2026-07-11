from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError

from tags_machine_core.web.errors import ApiError


router = APIRouter()


@router.post("/compose-preview")
def compose_preview(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    api = request.app.state.generation_api
    try:
        return api.resolve_compose_render_plan(payload)
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        raise ApiError(
            code="compose_preview_failed",
            message=str(exc),
            status_code=400,
        ) from exc
