from __future__ import annotations

import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from tags_machine_core.web.errors import ApiError
from tags_machine_core.web.services.job_manager import JobManager


router = APIRouter()


def _manager(request: Request) -> JobManager:
    return request.app.state.job_manager


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    try:
        return _manager(request).get(job_id).to_dict()
    except KeyError as exc:
        raise ApiError(
            code="job_not_found",
            message=f"Job not found: {job_id}",
            status_code=404,
        ) from exc


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict:
    try:
        return _manager(request).cancel(job_id).to_dict()
    except KeyError as exc:
        raise ApiError(
            code="job_not_found",
            message=f"Job not found: {job_id}",
            status_code=404,
        ) from exc


@router.get("/jobs/{job_id}/events")
def job_events(job_id: str, request: Request) -> StreamingResponse:
    manager = _manager(request)
    try:
        manager.get(job_id)
    except KeyError as exc:
        raise ApiError(
            code="job_not_found",
            message=f"Job not found: {job_id}",
            status_code=404,
        ) from exc

    def stream():
        last_index = 0
        while True:
            job = manager.get(job_id)
            events = job.events[last_index:]
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            last_index += len(events)
            if job.status in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.1)

    return StreamingResponse(stream(), media_type="text/event-stream")
