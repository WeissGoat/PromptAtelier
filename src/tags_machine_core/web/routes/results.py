from __future__ import annotations

import subprocess
import sys

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from tags_machine_core.web.errors import ApiError
from tags_machine_core.web.services.result_index import ResultIndex


router = APIRouter()


def _index(request: Request) -> ResultIndex:
    return request.app.state.result_index


@router.get("/results/runs")
def list_runs(request: Request) -> dict:
    return {
        "schema": "tags-machine-core.web.result-runs/v1",
        "runs": _index(request).list_runs(),
    }


@router.get("/results/task")
def get_task(task_dir: str, request: Request) -> dict:
    return _index(request).get_task(task_dir)


@router.get("/results/file")
def read_file(path: str, request: Request):
    try:
        return _index(request).read_file(path)
    except FileNotFoundError as exc:
        raise ApiError(
            code="result_file_not_found",
            message=f"Result file not found: {path}",
            status_code=404,
        ) from exc


@router.get("/results/image")
def read_image(path: str, request: Request) -> FileResponse:
    try:
        return FileResponse(_index(request).resolve_image(path))
    except FileNotFoundError as exc:
        raise ApiError(
            code="result_image_not_found",
            message=f"Result image not found: {path}",
            status_code=404,
        ) from exc
@router.get("/results/image-metadata")
def read_image_metadata(path: str, request: Request) -> dict:
    try:
        return _index(request).image_metadata(path)
    except FileNotFoundError as exc:
        raise ApiError(
            code="result_image_not_found",
            message=f"Result image not found: {path}",
            status_code=404,
        ) from exc
    except (OSError, ValueError) as exc:
        raise ApiError(
            code="image_metadata_unreadable",
            message=str(exc),
            status_code=400,
        ) from exc


@router.get("/results/image-parameter-diff")
def read_image_parameter_diff(
    previous_path: str,
    current_path: str,
    request: Request,
) -> dict:
    try:
        return _index(request).image_parameter_diff(previous_path, current_path)
    except FileNotFoundError as exc:
        raise ApiError(
            code="result_image_not_found",
            message="Previous or current result image was not found",
            status_code=404,
        ) from exc
    except (OSError, ValueError) as exc:
        raise ApiError(
            code="image_parameter_diff_unreadable",
            message=str(exc),
            status_code=400,
        ) from exc


@router.post("/results/open-image-folder")
def open_image_folder(data: dict, request: Request) -> dict:
    path = str(data.get("path") or "").strip()
    if not path:
        raise ApiError(
            code="result_image_required",
            message="results/open-image-folder requires path",
            status_code=400,
        )
    try:
        target = _index(request).resolve_image(path)
    except FileNotFoundError as exc:
        raise ApiError(
            code="result_image_not_found",
            message=f"Result image not found: {path}",
            status_code=404,
        ) from exc
    if sys.platform != "win32":
        raise ApiError(
            code="desktop_integration_unsupported",
            message="Opening an image folder is currently supported on Windows only",
            status_code=501,
        )
    try:
        subprocess.Popen(
            ["explorer.exe", "/select,", str(target)],
            close_fds=True,
        )
    except OSError as exc:
        raise ApiError(
            code="open_image_folder_failed",
            message=str(exc),
            status_code=500,
        ) from exc
    return {
        "schema": "tags-machine-core.web.open-image-folder/v1",
        "opened": True,
        "path": str(target),
    }
