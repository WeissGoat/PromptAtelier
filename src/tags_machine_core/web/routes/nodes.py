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
