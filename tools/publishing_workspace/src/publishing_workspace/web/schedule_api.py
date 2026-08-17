from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..catalog.repository import CatalogRepository
from ..config import load_workspace
from ..plans.models import ScheduleEntry
from ..plans.repository import PlanRevisionConflictError
from ..plans.search import AssetSearchFilter, AssetSearchService, FACET_FIELDS
from ..plans.service import PlanLockedError, PlanValidationError
from ..service import PublishingService


class EntryMutation(BaseModel):
    revision: int | None = Field(default=None, ge=1)
    entry: ScheduleEntry


class DateMutation(BaseModel):
    revision: int | None = Field(default=None, ge=1)
    target_date: date


class RevisionMutation(BaseModel):
    revision: int | None = Field(default=None, ge=1)


def create_app(root: str | Path) -> FastAPI:
    app = FastAPI(title="Publishing Workspace Schedule API")
    app.state.publishing_root = Path(root).expanduser().resolve()

    @app.exception_handler(PlanRevisionConflictError)
    async def revision_conflict(_, exc: PlanRevisionConflictError):
        return _json_error(409, "plan_revision_conflict", str(exc))

    @app.exception_handler(PlanLockedError)
    async def locked_plan(_, exc: PlanLockedError):
        return _json_error(409, "plan_locked", str(exc))

    @app.exception_handler(PlanValidationError)
    async def invalid_plan(_, exc: PlanValidationError):
        return _json_error(422, "plan_validation_error", str(exc))

    @app.exception_handler(KeyError)
    async def missing_resource(_, exc: KeyError):
        return _json_error(404, "not_found", str(exc))

    @app.exception_handler(ValueError)
    async def invalid_request(_, exc: ValueError):
        return _json_error(422, "invalid_request", str(exc))

    @app.get("/api/plans/{month}")
    def get_plan(month: str):
        return PublishingService().schedule_show(app.state.publishing_root, month).model_dump(
            mode="json", by_alias=True
        )

    @app.post("/api/plans/{month}/entries")
    def add_entry(month: str, payload: EntryMutation):
        return PublishingService().schedule_add_entry(
            app.state.publishing_root,
            month,
            payload.entry,
            expected_revision=payload.revision,
        ).model_dump(mode="json", by_alias=True)

    @app.put("/api/plans/{month}/entries/{entry_id}")
    def update_entry(month: str, entry_id: str, payload: EntryMutation):
        if payload.entry.entry_id != entry_id:
            raise ValueError("URL entry_id 与 body entry_id 不一致")
        return PublishingService().schedule_update_entry(
            app.state.publishing_root,
            month,
            payload.entry,
            expected_revision=payload.revision,
        ).model_dump(mode="json", by_alias=True)

    @app.patch("/api/plans/{month}/entries/{entry_id}/date")
    def move_entry_date(month: str, entry_id: str, payload: DateMutation):
        return PublishingService().schedule_move_date(
            app.state.publishing_root,
            month,
            entry_id,
            payload.target_date,
            expected_revision=payload.revision,
        ).model_dump(mode="json", by_alias=True)

    @app.delete("/api/plans/{month}/entries/{entry_id}")
    def delete_entry(month: str, entry_id: str, revision: int | None = Query(default=None, ge=1)):
        return PublishingService().schedule_delete_entry(
            app.state.publishing_root,
            month,
            entry_id,
            expected_revision=revision,
        ).model_dump(mode="json", by_alias=True)

    @app.post("/api/plans/{month}/lock")
    def lock_plan(month: str, payload: RevisionMutation):
        return PublishingService().schedule_lock(
            app.state.publishing_root,
            month,
            expected_revision=payload.revision,
        ).model_dump(mode="json", by_alias=True)

    @app.post("/api/plans/{month}/unlock")
    def unlock_plan(month: str, payload: RevisionMutation):
        return PublishingService().schedule_unlock(
            app.state.publishing_root,
            month,
            expected_revision=payload.revision,
        ).model_dump(mode="json", by_alias=True)

    @app.get("/api/assets/search")
    def search_assets(
        import_id: str | None = None,
        text: str = "",
        artist: str | None = None,
        character: str | None = None,
        action_group: str | None = None,
        action: str | None = None,
        facets: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
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
        query = AssetSearchFilter(
            import_id=import_id,
            text=text,
            artist=artist,
            character=character,
            action_group=action_group,
            action=action,
            facets=parsed_facets,
            limit=limit,
        )
        return [
            item.model_dump(mode="json")
            for item in AssetSearchService().search(app.state.publishing_root, query)
        ]

    @app.get("/api/assets/facets")
    def asset_facets(import_id: str | None = None):
        return AssetSearchService().facets(app.state.publishing_root, import_id=import_id)

    @app.get("/api/assets/{asset_id}/preview")
    def asset_preview(asset_id: str):
        paths, _ = load_workspace(app.state.publishing_root)
        catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        asset = next(
            (item for item in catalog.assets_for_import() if item.asset_id == asset_id),
            None,
        )
        if asset is None or not Path(asset.path).is_file():
            raise KeyError(f"Catalog 中找不到可预览资产：{asset_id}")
        return FileResponse(asset.path)

    return app


def _json_error(status_code: int, code: str, message: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": code, "message": message}},
    )
