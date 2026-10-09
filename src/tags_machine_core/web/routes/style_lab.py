from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from tags_machine_core.json_tools import sanitize_json_for_display
from tags_machine_core.llm import LLMError, translate_tags
from tags_machine_core.style_lab import RegenSettings, StyleLabService, WorkspaceInfo, WorkspaceStore
from tags_machine_core.style_lab.metadata import IMAGE_SUFFIXES, read_source_parameters
from tags_machine_core.web.errors import ApiError


router = APIRouter(prefix="/style-lab")

MAX_TRANSLATE_TEXTS = 2000


def _store(request: Request) -> WorkspaceStore:
    return request.app.state.style_lab_store


def _service(request: Request) -> StyleLabService:
    return request.app.state.style_lab_service


def _workspace(request: Request, workspace_id: str) -> WorkspaceInfo:
    try:
        return _store(request).get(workspace_id)
    except KeyError as exc:
        raise ApiError(code="workspace_not_found", message=f"Workspace not found: {workspace_id}", status_code=404) from exc


def _pretranslate(request: Request, info: WorkspaceInfo) -> str | None:
    # 翻译只是增强，起不来不影响打开工作区。
    try:
        return _service(request).start_pretranslate(info)
    except Exception:  # noqa: BLE001
        return None


def _workspace_payload(store: WorkspaceStore, info: WorkspaceInfo) -> dict[str, Any]:
    index = store.load_index(info)
    return {
        "schema": "tags-machine-core.web.style-lab-workspace/v1",
        "workspace": info.model_dump(mode="json", by_alias=True),
        "scanned_at": index.scanned_at,
        "images": [record.model_dump(mode="json") for record in index.images],
    }


@router.get("/workspaces")
def list_workspaces(request: Request) -> dict[str, Any]:
    return {
        "schema": "tags-machine-core.web.style-lab-workspaces/v1",
        "workspaces": [item.model_dump(mode="json", by_alias=True) for item in _store(request).list_workspaces()],
    }


@router.post("/workspaces")
def open_workspace(data: dict[str, Any], request: Request) -> dict[str, Any]:
    store = _store(request)
    root = str(data.get("root") or "").strip().strip('"')
    files = data.get("files")
    name = str(data.get("name") or "").strip() or None
    try:
        if root:
            info = store.open_folder(root, name=name)
        elif isinstance(files, list):
            info = store.open_files([str(item).strip().strip('"') for item in files], name=name)
        else:
            raise ApiError(code="invalid_workspace", message="Provide root or files", status_code=400)
    except FileNotFoundError as exc:
        raise ApiError(code="workspace_source_not_found", message=str(exc), status_code=404) from exc
    index = store.load_index(info)
    stats = None
    if index.scanned_at is None or data.get("rescan"):
        _, stats = store.scan(info)
    return {**_workspace_payload(store, info), "scan": stats, "pretranslate_job_id": _pretranslate(request, info)}


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, request: Request) -> dict[str, Any]:
    return _workspace_payload(_store(request), _workspace(request, workspace_id))


@router.post("/workspaces/{workspace_id}/scan")
def scan_workspace(workspace_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    info = _workspace(request, workspace_id)
    _, stats = store.scan(info)
    return {**_workspace_payload(store, info), "scan": stats, "pretranslate_job_id": _pretranslate(request, info)}


@router.post("/workspaces/{workspace_id}/pretranslate")
def pretranslate(workspace_id: str, request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    return {"job_id": _service(request).start_pretranslate(info)}


@router.post("/workspaces/{workspace_id}/upload")
async def upload_images(workspace_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    info = _workspace(request, workspace_id)
    if info.kind != "files":
        raise ApiError(code="upload_not_supported", message="Only image-group workspaces accept uploads", status_code=400)
    form = await request.form()
    uploads = store.uploads_dir(info)
    uploads.mkdir(parents=True, exist_ok=True)
    saved = 0
    for item in form.getlist("files"):
        filename = getattr(item, "filename", None)
        if not filename or not hasattr(item, "read"):
            continue
        clean = re.sub(r'[\\/*?:"<>|]', "_", Path(filename).name)
        if Path(clean).suffix.lower() not in IMAGE_SUFFIXES:
            continue
        target = uploads / clean
        if target.exists():
            target = uploads / f"{target.stem}_{int(time.time() * 1000)}{target.suffix}"
        target.write_bytes(await item.read())
        saved += 1
    if saved == 0:
        raise ApiError(code="no_images_uploaded", message="No PNG/WebP/JPEG files in upload", status_code=400)
    _, stats = store.scan(info)
    return {
        **_workspace_payload(store, info),
        "scan": stats,
        "uploaded": saved,
        "pretranslate_job_id": _pretranslate(request, info),
    }


@router.get("/workspaces/{workspace_id}/images/{image_id}")
def get_image_detail(workspace_id: str, image_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    info = _workspace(request, workspace_id)
    try:
        record = store.find_image(info, image_id)
    except KeyError as exc:
        raise ApiError(code="image_not_found", message=f"Image not found: {image_id}", status_code=404) from exc
    params, png_text = read_source_parameters(Path(record.path))
    return {
        "schema": "tags-machine-core.web.style-lab-image/v1",
        "image": record.model_dump(mode="json"),
        "raw_parameters": sanitize_json_for_display(params),
        "png_text_keys": sorted(png_text),
    }


@router.get("/workspaces/{workspace_id}/file")
def read_workspace_file(
    workspace_id: str,
    request: Request,
    image_id: str | None = None,
    path: str | None = None,
    size: int = 0,
) -> FileResponse:
    store = _store(request)
    info = _workspace(request, workspace_id)
    if image_id:
        try:
            target = Path(store.find_image(info, image_id).path)
        except KeyError as exc:
            raise ApiError(code="image_not_found", message=f"Image not found: {image_id}", status_code=404) from exc
    elif path:
        target = Path(path)
        if not store.is_allowed_file(info, target):
            raise ApiError(code="file_not_in_workspace", message=f"File is not part of this workspace: {path}", status_code=403)
    else:
        raise ApiError(code="missing_file", message="Provide image_id or path", status_code=400)
    if not target.is_file():
        raise ApiError(code="file_not_found", message=f"File not found: {target}", status_code=404)
    if size > 0:
        try:
            thumb = request.app.state.result_index.thumbnail_for(target, size)
        except OSError as exc:
            raise ApiError(code="thumbnail_failed", message=str(exc), status_code=400) from exc
        media_type = "image/webp" if thumb.suffix.lower() == ".webp" else None
        return FileResponse(thumb, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})
    return FileResponse(target)


@router.post("/workspaces/{workspace_id}/regenerate")
def regenerate(workspace_id: str, data: dict[str, Any], request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    image_id = str(data.get("image_id") or "")
    try:
        settings = RegenSettings.model_validate(data.get("settings") or {})
    except ValidationError as exc:
        raise ApiError(code="invalid_regen_settings", message=str(exc), status_code=400) from exc
    try:
        run = _service(request).start_regenerate(info, image_id, settings)
    except KeyError as exc:
        raise ApiError(code="image_not_found", message=f"Image not found: {image_id}", status_code=404) from exc
    except ValueError as exc:
        raise ApiError(code="regenerate_failed", message=str(exc), status_code=400) from exc
    return {"schema": "tags-machine-core.web.style-lab-run/v1", "run": run}


@router.get("/workspaces/{workspace_id}/runs")
def list_runs(workspace_id: str, request: Request, image_id: str | None = None) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    service = _service(request)
    runs = [service.reconcile_run(info, run) for run in _store(request).list_runs(info, image_id=image_id)]
    return {"schema": "tags-machine-core.web.style-lab-runs/v1", "runs": runs}


@router.get("/workspaces/{workspace_id}/runs/{run_id}")
def get_run(workspace_id: str, run_id: str, request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    try:
        run = _store(request).get_run(info, run_id)
    except KeyError as exc:
        raise ApiError(code="run_not_found", message=f"Run not found: {run_id}", status_code=404) from exc
    return {"schema": "tags-machine-core.web.style-lab-run/v1", "run": _service(request).reconcile_run(info, run)}


@router.get("/llm/status")
def llm_status(request: Request) -> dict[str, Any]:
    return {"schema": "tags-machine-core.web.llm-status/v1", **request.app.state.llm_client.status()}


@router.post("/translate")
def translate(data: dict[str, Any], request: Request) -> dict[str, Any]:
    texts = data.get("texts")
    if not isinstance(texts, list) or not all(isinstance(item, str) for item in texts):
        raise ApiError(code="invalid_translate_request", message="texts must be a list of strings", status_code=400)
    if len(texts) > MAX_TRANSLATE_TEXTS:
        raise ApiError(
            code="invalid_translate_request",
            message=f"At most {MAX_TRANSLATE_TEXTS} texts per request",
            status_code=400,
        )
    client = request.app.state.llm_client
    try:
        translations = translate_tags(client, texts)
    except LLMError as exc:
        raise ApiError(code="translate_failed", message=str(exc), status_code=502) from exc
    return {
        "schema": "tags-machine-core.web.translations/v1",
        "available": client.available,
        "translations": translations,
    }
