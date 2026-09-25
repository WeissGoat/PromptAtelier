from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from tags_machine_core.web.errors import ApiError

router = APIRouter()

AUTOSAVE_PATH = Path("output") / ".compare_workspace_autosave.json"


@router.get("/compare/workspace")
def get_compare_workspace() -> dict[str, Any]:
    if not AUTOSAVE_PATH.is_file():
        raise ApiError(
            code="workspace_not_found",
            message="No autosaved compare workspace found on server",
            status_code=404,
        )
    try:
        content = AUTOSAVE_PATH.read_text(encoding="utf-8")
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("Autosave content is not a valid JSON object")
        return data
    except Exception as exc:
        raise ApiError(
            code="workspace_read_failed",
            message=f"Failed to read autosaved compare workspace: {exc}",
            status_code=500,
        ) from exc


@router.post("/compare/workspace")
async def save_compare_workspace(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise ApiError(
            code="invalid_json",
            message="Request body must be valid JSON",
            status_code=400,
        ) from exc

    if not isinstance(body, dict) or "rounds" not in body:
        raise ApiError(
            code="invalid_workspace",
            message="Workspace snapshot must contain 'rounds'",
            status_code=400,
        )

    try:
        AUTOSAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Write to temporary file first then atomic rename
        temp_path = AUTOSAVE_PATH.with_suffix(".tmp")
        temp_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(AUTOSAVE_PATH)
        return {"status": "saved", "round_count": len(body.get("rounds", []))}
    except Exception as exc:
        raise ApiError(
            code="workspace_write_failed",
            message=f"Failed to write compare workspace autosave: {exc}",
            status_code=500,
        ) from exc


@router.delete("/compare/workspace")
def clear_compare_workspace() -> dict[str, Any]:
    if AUTOSAVE_PATH.is_file():
        try:
            AUTOSAVE_PATH.unlink()
        except OSError as exc:
            raise ApiError(
                code="workspace_delete_failed",
                message=f"Failed to delete autosaved compare workspace: {exc}",
                status_code=500,
            ) from exc
    return {"status": "cleared"}
