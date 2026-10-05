from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from tags_machine_core.web.errors import ApiError
from tags_machine_core.web.services.generate_batch import GENERATE_BATCH_JOB
from tags_machine_core.web.services.output_history import OutputHistory
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


def _history(request: Request) -> OutputHistory:
    return request.app.state.output_history


def _jobs_by_output_dir(request: Request) -> dict[str, dict]:
    """出图历史里给批次配上提交时的任务名（如"Random · 3 轮"）；只有后端记得的任务才有。"""
    history = _history(request)
    jobs: dict[str, dict] = {}
    for job in request.app.state.job_manager.list(name=GENERATE_BATCH_JOB, limit=500):
        result = job.result if isinstance(job.result, dict) else {}
        output_dir = result.get("output_dir")
        if not output_dir:
            continue
        resolved = Path(output_dir)
        if not resolved.is_absolute():
            resolved = Path.cwd() / resolved
        try:
            run_id = resolved.resolve().relative_to(history.root).as_posix()
        except ValueError:
            continue
        jobs[run_id] = {"id": job.id, "label": result.get("label"), "status": job.status}
    return jobs


@router.get("/history/runs")
def list_history_runs(request: Request) -> dict:
    runs = _history(request).list_runs()
    jobs = _jobs_by_output_dir(request)
    for run in runs:
        run["job"] = jobs.get(run["id"])
    return {"schema": "tags-machine-core.web.history-runs/v1", "runs": runs}


@router.get("/history/images")
def list_history_images(run_id: str, request: Request, offset: int = 0, limit: int = 300) -> dict:
    try:
        return _history(request).run_images(run_id, offset=max(0, offset), limit=max(1, min(limit, 1000)))
    except FileNotFoundError as exc:
        raise ApiError(code="history_run_not_found", message=f"History run not found: {run_id}", status_code=404) from exc


@router.get("/results/thumb")
def read_thumbnail(path: str, request: Request, size: int = 320) -> FileResponse:
    try:
        thumb = _index(request).thumbnail(path, size)
    except FileNotFoundError as exc:
        raise ApiError(
            code="result_image_not_found",
            message=f"Result image not found: {path}",
            status_code=404,
        ) from exc
    except OSError as exc:
        raise ApiError(code="thumbnail_failed", message=str(exc), status_code=400) from exc
    media_type = "image/webp" if thumb.suffix.lower() == ".webp" else None
    return FileResponse(thumb, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})


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
    except FileNotFoundError:
        direct_path = Path(path)
        if direct_path.is_file() and direct_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            target = direct_path.resolve()
        else:
            raise ApiError(
                code="result_image_not_found",
                message=f"Result image not found: {path}",
                status_code=404,
            )
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
