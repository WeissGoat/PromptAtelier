from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError

from tags_machine_core.node_pools import NodePoolSpec
from tags_machine_core.web.errors import ApiError


router = APIRouter()


@router.get("/node-pools/collections")
def list_collections(role: str, request: Request) -> dict[str, Any]:
    try:
        return {
            "schema": "tags-machine-core.web.node-pool-collections/v1",
            "role": role,
            "items": request.app.state.node_pool_service.collections(role),
        }
    except (FileNotFoundError, ValueError) as exc:
        raise ApiError(code="node_pool_collections_failed", message=str(exc), status_code=400) from exc


@router.post("/node-pools/scan")
def scan_node_pool(data: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        return request.app.state.node_pool_service.scan(
            role=str(data.get("role") or "").strip(),
            spec=NodePoolSpec.model_validate(data.get("spec") or {}),
            query=str(data.get("q") or ""),
            offset=int(data.get("offset") or 0),
            limit=int(data.get("limit") or 20),
            refresh=bool(data.get("refresh", False)),
        )
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        raise ApiError(code="node_pool_scan_failed", message=str(exc), status_code=400) from exc


@router.post("/node-pools/sample")
def sample_node_pool(data: dict[str, Any], request: Request) -> dict[str, Any]:
    try:
        return request.app.state.node_pool_service.sample(
            role=str(data.get("role") or "").strip(),
            spec=NodePoolSpec.model_validate(data.get("spec") or {}),
            count=int(data.get("count") or 1),
        )
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        raise ApiError(code="node_pool_sample_failed", message=str(exc), status_code=400) from exc
