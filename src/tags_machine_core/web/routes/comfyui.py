from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request


router = APIRouter()


@router.get("/comfyui/targets")
def list_comfyui_targets(request: Request) -> dict[str, Any]:
    return request.app.state.comfyui_targets.describe()
