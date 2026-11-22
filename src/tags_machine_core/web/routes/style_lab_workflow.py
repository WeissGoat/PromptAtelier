"""Custom grouping, analysis preparation, and explicitly started snapshot tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Query, Request

from tags_machine_core.style_lab.custom_groups import (
    CustomGroups,
    CustomGroupStore,
    GroupConflictError,
)
from tags_machine_core.style_lab.preparation import PreparationService
from tags_machine_core.style_lab.test_plans import TestPlanService

from ..errors import ApiError
from .style_lab import _service, _shelf, _workspace

router = APIRouter(prefix="/style-lab/workspaces/{workspace_id}")


def _call(action: Callable[[], Any]):
    try:
        return action()
    except GroupConflictError as exc:
        raise ApiError(code="style_lab_conflict", message=str(exc), status_code=409) from exc
    except KeyError as exc:
        raise ApiError(
            code="style_lab_record_not_found", message=str(exc), status_code=404
        ) from exc
    except (ValueError, OSError) as exc:
        raise ApiError(
            code="invalid_style_lab_workflow", message=str(exc), status_code=400
        ) from exc


@router.get("/custom-groups")
def get_groups(workspace_id: str, request: Request):
    info = _workspace(request, workspace_id)
    return _call(lambda: CustomGroupStore(_service(request).store, info).payload())


@router.put("/custom-groups")
def save_groups(workspace_id: str, data: dict[str, Any], request: Request):
    info = _workspace(request, workspace_id)

    def action():
        groups = CustomGroupStore(_service(request).store, info)
        actor = data.get("actor", "user")
        if actor not in {"user", "agent"}:
            raise ValueError("actor 必须是 user 或 agent")
        groups.save(CustomGroups.model_validate(data), actor=actor)
        return groups.payload()

    return _call(action)


@router.get("/analysis-context")
def analysis_context(
    workspace_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
):
    info = _workspace(request, workspace_id)
    return _call(lambda: PreparationService(_service(request), info).context(offset, limit))


@router.post("/preparations")
def prepare(workspace_id: str, data: dict[str, Any], request: Request):
    info = _workspace(request, workspace_id)
    return _call(lambda: PreparationService(_service(request), info).apply(data))


@router.get("/preparations/{preparation_id}")
def get_preparation(workspace_id: str, preparation_id: str, request: Request):
    info = _workspace(request, workspace_id)
    return _call(lambda: PreparationService(_service(request), info).get(preparation_id))


@router.post("/test-plans")
def create_test_plan(workspace_id: str, data: dict[str, Any], request: Request):
    info = _workspace(request, workspace_id)
    service = TestPlanService(_service(request), info)
    return _call(lambda: service.public(service.create(data, _shelf(request).load())))


@router.get("/test-plans")
def list_test_plans(workspace_id: str, request: Request):
    info = _workspace(request, workspace_id)
    service = TestPlanService(_service(request), info)
    return _call(lambda: {"plans": [service.public(plan) for plan in service.list()]})


@router.get("/test-plans/{plan_id}")
def get_test_plan(workspace_id: str, plan_id: str, request: Request):
    info = _workspace(request, workspace_id)
    service = TestPlanService(_service(request), info)
    return _call(lambda: service.public(service.get(plan_id)))


@router.post("/test-plans/{plan_id}/start")
def start_test_plan(workspace_id: str, plan_id: str, request: Request):
    info = _workspace(request, workspace_id)
    service = TestPlanService(_service(request), info)
    return _call(lambda: service.public(service.start(plan_id)))
