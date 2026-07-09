from __future__ import annotations

from fastapi import APIRouter, Request

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
