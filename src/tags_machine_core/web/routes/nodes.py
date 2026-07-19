from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import ValidationError

from tags_machine_core.web.errors import ApiError
from tags_machine_core.web.services.node_workspace import NodeWorkspace
from tags_machine_core.web.services.node_save_preview_store import (
    SavePreviewExpiredError,
    SourceChangedError,
)


router = APIRouter()


def _workspace(request: Request) -> NodeWorkspace:
    return request.app.state.node_workspace


def _save_previews(request: Request):
    return request.app.state.node_save_previews


@router.get("/nodes")
def list_nodes(
    role: str,
    request: Request,
    q: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> dict:
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    nodes, has_more = _workspace(request).list_nodes_page(
        role,
        query=q,
        offset=offset,
        limit=limit,
    )
    return {
        "schema": "tags-machine-core.web.node-list/v1",
        "role": role,
        "nodes": nodes,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
    }


@router.get("/nodes/read")
def read_node(ref: str, request: Request, role: str | None = None) -> dict:
    try:
        return _workspace(request).read_node(ref, role=role)
    except FileNotFoundError as exc:
        raise ApiError(code="node_not_found", message=str(exc), status_code=404) from exc


@router.post("/nodes/preview")
def preview_node(data: dict, request: Request) -> dict:
    node = data.get("node")
    if not isinstance(node, dict):
        raise ApiError(code="invalid_node", message="nodes/preview requires node", status_code=400)
    try:
        return _workspace(request).preview_node(node)
    except ValidationError as exc:
        raise ApiError(code="invalid_node", message=str(exc), status_code=400) from exc


@router.post("/nodes/editor-preview")
def preview_node_editor(data: dict, request: Request) -> dict:
    ref = str(data.get("ref") or "").strip()
    role = str(data.get("role") or "").strip()
    values = data.get("values")
    if not ref or not role or not isinstance(values, dict):
        raise ApiError(code="invalid_editor_values", message="nodes/editor-preview requires ref, role and values", status_code=400)
    try:
        return _workspace(request).preview_editor(ref, role=role, values=values)
    except (ValidationError, ValueError) as exc:
        raise ApiError(code="invalid_editor_values", message=str(exc), status_code=400) from exc


@router.post("/nodes/save-preview")
def preview_node_save(data: dict, request: Request) -> dict:
    ref = str(data.get("ref") or "").strip()
    role = str(data.get("role") or "").strip()
    values = data.get("values")
    if not ref or not role or not isinstance(values, dict):
        raise ApiError(code="invalid_editor_values", message="nodes/save-preview requires ref, role and values", status_code=400)
    try:
        node, mutations = _workspace(request).preview_file_mutations(ref, role=role, values=values)
        preview = _save_previews(request).create(
            ref=str(_workspace(request).resolve_node_path(ref)),
            role=role,
            node=node,
            mutations=mutations,
        )
        return {
            "schema": "tags-machine-core.web.node-save-preview/v1",
            "preview_id": preview.preview_id,
            "node": node.model_dump(mode="json"),
            "files": [
                _workspace(request).mutation_payload(mutation, node_dir=preview.ref)
                for mutation in mutations
            ],
            "warnings": [],
            "expires_at": preview.expires_at,
        }
    except (ValidationError, ValueError) as exc:
        raise ApiError(code="invalid_editor_values", message=str(exc), status_code=400) from exc


@router.put("/nodes/save-commit")
def commit_node_save(data: dict, request: Request) -> dict:
    preview_id = str(data.get("preview_id") or "").strip()
    if not preview_id:
        raise ApiError(code="save_preview_required", message="nodes/save-commit requires preview_id", status_code=400)
    try:
        preview = _save_previews(request).get(preview_id)
        _workspace(request).commit_file_mutations(preview.mutations)
        _save_previews(request).consume(preview_id)
        return _workspace(request).read_node(preview.ref, role=preview.role)
    except SavePreviewExpiredError as exc:
        raise ApiError(code="save_preview_expired", message=str(exc), status_code=409) from exc
    except SourceChangedError as exc:
        raise ApiError(code="source_changed", message=str(exc), status_code=409) from exc
    except OSError as exc:
        raise ApiError(code="source_write_failed", message=str(exc), status_code=500) from exc


@router.put("/nodes/save")
def save_node(data: dict, request: Request) -> dict:
    ref = str(data.get("ref") or "").strip()
    node = data.get("node")
    if not ref or not isinstance(node, dict):
        raise ApiError(code="invalid_node", message="nodes/save requires ref and node", status_code=400)
    try:
        return _workspace(request).save_node(ref, node)
    except (ValidationError, ValueError) as exc:
        raise ApiError(code="invalid_node", message=str(exc), status_code=400) from exc
