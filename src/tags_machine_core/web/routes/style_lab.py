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
from tags_machine_core.style_lab.artist_test import ArtistTestSettings
from tags_machine_core.style_lab.export import ExportConflictError, ExportError, ExportRequest
from tags_machine_core.style_lab.recipe import Recipe, RecipeConflictError
from tags_machine_core.style_lab.tokens import tokenize
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


def _analyze(request: Request, info: WorkspaceInfo) -> str | None:
    # 翻译和分类只是增强，起不来不影响打开工作区。
    try:
        return _service(request).start_analysis(info)
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
    return {**_workspace_payload(store, info), "scan": stats, "analysis_job_id": _analyze(request, info)}


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, request: Request) -> dict[str, Any]:
    return _workspace_payload(_store(request), _workspace(request, workspace_id))


@router.post("/workspaces/{workspace_id}/scan")
def scan_workspace(workspace_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    info = _workspace(request, workspace_id)
    _, stats = store.scan(info)
    return {**_workspace_payload(store, info), "scan": stats, "analysis_job_id": _analyze(request, info)}


@router.post("/workspaces/{workspace_id}/analyze")
def analyze(workspace_id: str, request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    return {"job_id": _service(request).start_analysis(info)}


@router.get("/workspaces/{workspace_id}/analysis")
def get_analysis(workspace_id: str, request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    return {"schema": "tags-machine-core.web.style-lab-analysis/v1", **_service(request).analysis(info)}


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
        "analysis_job_id": _analyze(request, info),
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
def list_runs(
    workspace_id: str, request: Request, image_id: str | None = None, recipe_id: str | None = None
) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    service = _service(request)
    runs = [
        service.reconcile_run(info, run)
        for run in _store(request).list_runs(info, image_id=image_id, recipe_id=recipe_id)
    ]
    return {"schema": "tags-machine-core.web.style-lab-runs/v1", "runs": runs}


@router.get("/workspaces/{workspace_id}/runs/{run_id}")
def get_run(workspace_id: str, run_id: str, request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    try:
        run = _store(request).get_run(info, run_id)
    except KeyError as exc:
        raise ApiError(code="run_not_found", message=f"Run not found: {run_id}", status_code=404) from exc
    return {"schema": "tags-machine-core.web.style-lab-run/v1", "run": _service(request).reconcile_run(info, run)}


def _recipe_summary(recipe: Recipe) -> dict[str, Any]:
    return {
        "id": recipe.id,
        "name": recipe.name,
        "version": recipe.version,
        "stage": recipe.stage,
        "locked": recipe.locked,
        "source_image_id": recipe.source_image_id,
        "group_id": recipe.group_id,
        "updated_at": recipe.updated_at,
    }


def _get_recipe(request: Request, info: WorkspaceInfo, recipe_id: str) -> Recipe:
    try:
        return _service(request).recipes(info).get(recipe_id)
    except KeyError as exc:
        raise ApiError(code="recipe_not_found", message=f"Recipe not found: {recipe_id}", status_code=404) from exc


def _parse_recipe(data: Any) -> Recipe:
    try:
        return Recipe.model_validate(data)
    except ValidationError as exc:
        raise ApiError(code="invalid_recipe", message=str(exc), status_code=400) from exc


@router.get("/workspaces/{workspace_id}/recipes")
def list_recipes(workspace_id: str, request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    return {"recipes": [_recipe_summary(recipe) for recipe in _service(request).recipes(info).list()]}


@router.post("/workspaces/{workspace_id}/recipes")
def create_recipe(workspace_id: str, data: dict[str, Any], request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    try:
        recipe = _service(request).create_recipe(
            info,
            str(data.get("image_id") or ""),
            name=str(data.get("name") or "").strip() or None,
            group_id=str(data.get("group_id") or "").strip() or None,
        )
    except KeyError as exc:
        raise ApiError(code="image_not_found", message=f"Image not found: {data.get('image_id')}", status_code=404) from exc
    except ValueError as exc:
        raise ApiError(code="recipe_create_failed", message=str(exc), status_code=400) from exc
    return {"recipe": recipe.model_dump(mode="json", by_alias=True)}


@router.post("/workspaces/{workspace_id}/recipes/preview")
def preview_recipe(workspace_id: str, data: dict[str, Any], request: Request) -> dict[str, Any]:
    """预览未保存的草稿：返回实际会发给 NovelAI 的提示词、负面和角色提示词。"""
    info = _workspace(request, workspace_id)
    recipe = _parse_recipe(data.get("recipe"))
    try:
        return {"preview": _service(request).preview_recipe(info, recipe)}
    except (ValueError, ValidationError, FileNotFoundError) as exc:
        raise ApiError(code="recipe_preview_failed", message=str(exc), status_code=400) from exc


@router.get("/workspaces/{workspace_id}/recipes/{recipe_id}")
def get_recipe(workspace_id: str, recipe_id: str, request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    recipe = _get_recipe(request, info, recipe_id)
    return {
        "recipe": recipe.model_dump(mode="json", by_alias=True),
        "history": _service(request).recipes(info).history(recipe_id),
    }


@router.put("/workspaces/{workspace_id}/recipes/{recipe_id}")
def save_recipe(workspace_id: str, recipe_id: str, data: dict[str, Any], request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    _get_recipe(request, info, recipe_id)
    recipe = _parse_recipe(data.get("recipe"))
    if recipe.id != recipe_id:
        raise ApiError(code="invalid_recipe", message="Recipe id does not match the URL", status_code=400)
    try:
        saved = _service(request).recipes(info).save(recipe, base_version=int(data.get("base_version") or 0))
    except RecipeConflictError as exc:
        raise ApiError(code="recipe_conflict", message=str(exc), status_code=409) from exc
    return {"recipe": saved.model_dump(mode="json", by_alias=True)}


@router.delete("/workspaces/{workspace_id}/recipes/{recipe_id}")
def delete_recipe(workspace_id: str, recipe_id: str, request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    try:
        _service(request).recipes(info).delete(recipe_id)
    except KeyError as exc:
        raise ApiError(code="recipe_not_found", message=f"Recipe not found: {recipe_id}", status_code=404) from exc
    return {"deleted": recipe_id}


@router.get("/workspaces/{workspace_id}/recipes/{recipe_id}/versions/{version}")
def get_recipe_version(workspace_id: str, recipe_id: str, version: int, request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    try:
        recipe = _service(request).recipes(info).get_version(recipe_id, version)
    except KeyError as exc:
        raise ApiError(code="recipe_not_found", message=str(exc), status_code=404) from exc
    return {"recipe": recipe.model_dump(mode="json", by_alias=True)}


@router.post("/workspaces/{workspace_id}/recipes/{recipe_id}/generate")
def generate_recipe(workspace_id: str, recipe_id: str, data: dict[str, Any], request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    _get_recipe(request, info, recipe_id)
    try:
        settings = RegenSettings.model_validate(data.get("settings") or {})
        run = _service(request).start_recipe_run(info, recipe_id, settings)
    except ValidationError as exc:
        raise ApiError(code="invalid_regen_settings", message=str(exc), status_code=400) from exc
    except ValueError as exc:
        raise ApiError(code="recipe_generate_failed", message=str(exc), status_code=400) from exc
    return {"schema": "tags-machine-core.web.style-lab-run/v1", "run": run}


@router.get("/library/node")
def library_node(ref: str, role: str, request: Request) -> dict[str, Any]:
    """素材卡片：节点的 tag 按部位分组，下划线换成空格，可直接放进提示词。"""
    if role not in {"character", "action"}:
        raise ApiError(code="invalid_role", message="role must be character or action", status_code=400)
    try:
        node = request.app.state.node_workspace.read_runtime_node(ref, role=role)
    except (FileNotFoundError, ValueError) as exc:
        raise ApiError(code="node_not_found", message=str(exc), status_code=404) from exc
    sections = []
    for name, tags in (node.tags or {}).items():
        cleaned = [_clean_library_tag(tag) for tag in tags if str(tag).strip()]
        if cleaned:
            sections.append({"name": name, "tags": list(dict.fromkeys(cleaned))})
    if not sections:
        texts = [fragment.text for fragment in node.prompt.positive if fragment.text.strip()]
        tokens = [token.text for text in texts for token in tokenize(text).tokens]
        if tokens:
            sections.append({"name": "prompt", "tags": list(dict.fromkeys(tokens))})
    return {
        "ref": ref,
        "role": role,
        "name": node.name or Path(ref).name,
        "sections": sections,
        "has_preview": request.app.state.node_workspace.preview_image(ref) is not None,
    }


def _clean_library_tag(tag: str) -> str:
    return " ".join(str(tag).replace("_", " ").split())


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


def _export_request(data: dict[str, Any]) -> ExportRequest:
    try:
        return ExportRequest.model_validate(data)
    except ValidationError as exc:
        raise ApiError(code="invalid_export_request", message=str(exc), status_code=400) from exc


@router.get("/workspaces/{workspace_id}/recipes/{recipe_id}/exports")
def recipe_exports(workspace_id: str, recipe_id: str, request: Request) -> dict[str, Any]:
    """导出对话框的初始值：建议的作者 id、以前的导出、可对比的已有画风。"""
    info = _workspace(request, workspace_id)
    _get_recipe(request, info, recipe_id)
    try:
        return _service(request).export_defaults(info, recipe_id)
    except ExportError as exc:
        raise ApiError(code="export_unavailable", message=str(exc), status_code=400) from exc


@router.post("/workspaces/{workspace_id}/recipes/{recipe_id}/export/preview")
def preview_export(workspace_id: str, recipe_id: str, data: dict[str, Any], request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    _get_recipe(request, info, recipe_id)
    try:
        return {"preview": _service(request).export_preview(info, recipe_id, _export_request(data))}
    except ExportError as exc:
        raise ApiError(code="invalid_export_request", message=str(exc), status_code=400) from exc


@router.post("/workspaces/{workspace_id}/recipes/{recipe_id}/export")
def export_recipe(workspace_id: str, recipe_id: str, data: dict[str, Any], request: Request) -> dict[str, Any]:
    """写入 design/画风/<目录>。expected_folder 是预览时看到的目录名，变了就拒绝，避免写到没看过的地方。"""
    info = _workspace(request, workspace_id)
    _get_recipe(request, info, recipe_id)
    expected = str(data.get("expected_folder") or "").strip() or None
    try:
        entry = _service(request).export_recipe(info, recipe_id, _export_request(data), expected_folder=expected)
    except ExportConflictError as exc:
        raise ApiError(code="export_conflict", message=str(exc), status_code=409) from exc
    except ExportError as exc:
        raise ApiError(code="export_failed", message=str(exc), status_code=400) from exc
    return {"export": entry}


@router.post("/workspaces/{workspace_id}/recipes/{recipe_id}/artist-test")
def artist_test(workspace_id: str, recipe_id: str, data: dict[str, Any], request: Request) -> dict[str, Any]:
    info = _workspace(request, workspace_id)
    _get_recipe(request, info, recipe_id)
    try:
        settings = ArtistTestSettings.model_validate(data.get("settings") or {})
    except ValidationError as exc:
        raise ApiError(code="invalid_artist_test", message=str(exc), status_code=400) from exc
    try:
        run = _service(request).start_artist_test(info, recipe_id, settings)
    except ValueError as exc:
        raise ApiError(code="artist_test_failed", message=str(exc), status_code=400) from exc
    return {"schema": "tags-machine-core.web.style-lab-run/v1", "run": run}
