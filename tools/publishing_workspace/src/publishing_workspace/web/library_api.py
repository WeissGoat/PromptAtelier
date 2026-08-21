from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..plans.search import AssetSearchFilter, AssetSearchService
from ..submissions.models import SubmissionRevisionConflictError
from ..submissions.service import SubmissionService


class SubmissionMutation(BaseModel):
    revision: int | None = Field(default=None, ge=1)
    title: str
    source_import_id: str | None = None
    sets: dict[str, list[str]]


def register_library_routes(app: FastAPI) -> None:
    """注册素材库与 Submission 相关的 HTTP API。"""

    @app.get("/api/library/assets")
    def search_library_assets(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=60, ge=1, le=200),
        import_id: str | None = None,
        text: str = "",
        artist: str | None = None,
        character: str | None = None,
        action_group: str | None = None,
        action: str | None = None,
        facets: str | None = None,
    ):
        parsed_facets: dict[str, set[str]] = {}
        if facets:
            try:
                raw = json.loads(facets)
            except json.JSONDecodeError as exc:
                raise ValueError(f"facets 必须是 JSON 对象：{exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError("facets 必须是 JSON 对象")
            parsed_facets = {
                str(field): set(values if isinstance(values, list) else [values])
                for field, values in raw.items()
            }

        filters = AssetSearchFilter(
            offset=offset,
            limit=limit,
            import_id=import_id,
            text=text,
            artist=artist,
            character=character,
            action_group=action_group,
            action=action,
            facets=parsed_facets,
        )
        return AssetSearchService().search_page(
            app.state.publishing_root, filters
        ).model_dump(mode="json", by_alias=True)

    @app.get("/api/library/facets")
    def library_facets(import_id: str | None = None):
        return AssetSearchService().facets(app.state.publishing_root, import_id=import_id)

    @app.get("/api/submissions")
    def list_submissions():
        return [
            item.model_dump(mode="json")
            for item in SubmissionService().list(app.state.publishing_root)
        ]

    @app.get("/api/submissions/{task_id}")
    def get_submission(task_id: str):
        try:
            return SubmissionService().get(
                app.state.publishing_root, task_id
            ).model_dump(mode="json")
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content={"detail": {"code": "task_not_found", "message": str(exc)}},
            )

    @app.post("/api/submissions")
    def create_submission(payload: SubmissionMutation):
        try:
            return SubmissionService().create_or_update(
                app.state.publishing_root,
                task_id=None,
                title=payload.title,
                source_import_id=payload.source_import_id,
                sets=payload.sets,
                expected_revision=payload.revision,
            ).model_dump(mode="json")
        except SubmissionRevisionConflictError as exc:
            return JSONResponse(
                status_code=409,
                content={"detail": {"code": "submission_revision_conflict", "message": str(exc)}},
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "invalid_submission", "message": str(exc)}},
            )
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "asset_unavailable", "message": str(exc)}},
            )

    @app.put("/api/submissions/{task_id}")
    def update_submission(task_id: str, payload: SubmissionMutation):
        try:
            return SubmissionService().create_or_update(
                app.state.publishing_root,
                task_id=task_id,
                title=payload.title,
                source_import_id=payload.source_import_id,
                sets=payload.sets,
                expected_revision=payload.revision,
            ).model_dump(mode="json")
        except SubmissionRevisionConflictError as exc:
            return JSONResponse(
                status_code=409,
                content={"detail": {"code": "submission_revision_conflict", "message": str(exc)}},
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "invalid_submission", "message": str(exc)}},
            )
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "asset_unavailable", "message": str(exc)}},
            )

    # 导出作业相关路由
    @app.post("/api/submissions/{task_id}/exports")
    def start_task_export(task_id: str):
        try:
            job = app.state.export_jobs.start(app.state.publishing_root, task_id)
            status_code = 202 if job.status == "queued" else 200
            return JSONResponse(
                status_code=status_code,
                content=job.model_dump(mode="json", by_alias=True),
            )
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content={"detail": {"code": "task_not_found", "message": str(exc)}},
            )

    @app.get("/api/export-jobs/{job_id}")
    def get_export_job(job_id: str):
        try:
            job = app.state.export_jobs.get(app.state.publishing_root, job_id)
            return job.model_dump(mode="json", by_alias=True)
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content={"detail": {"code": "export_job_not_found", "message": str(exc)}},
            )

    @app.get("/api/submissions/{task_id}/exports")
    def list_task_exports(task_id: str):
        jobs = app.state.export_jobs.list_for_task(app.state.publishing_root, task_id)
        return [job.model_dump(mode="json", by_alias=True) for job in jobs]

    @app.post("/api/export-jobs/{job_id}/open-output")
    def open_export_output(job_id: str):
        from ..export_jobs.models import ExportOutputNotFoundError, ExportOutputOpenError

        try:
            output_dir = app.state.export_jobs.open_output(app.state.publishing_root, job_id)
            return {"output_dir": output_dir}
        except ExportOutputNotFoundError as exc:
            return JSONResponse(
                status_code=404,
                content={"detail": {"code": "export_output_not_found", "message": str(exc)}},
            )
        except ExportOutputOpenError as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "detail": {
                        "code": "export_output_open_failed",
                        "message": str(exc),
                        "output_dir": exc.output_dir,
                    }
                },
            )
