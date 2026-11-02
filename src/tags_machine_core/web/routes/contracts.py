"""Agent 拼接契约的 Web 接口（docs/agent_compose_contract_spec_v1.md §10）。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError

from tags_machine_core.compose_contracts import ContractConflictError, ContractService
from tags_machine_core.compose_contracts.parser import ContractParseError
from tags_machine_core.web.errors import ApiError


router = APIRouter()


def _service(request: Request) -> ContractService:
    return request.app.state.contract_service


def _call(operation):
    try:
        return operation()
    except ContractConflictError as exc:
        raise ApiError(
            code="contract_conflict",
            message=str(exc),
            status_code=409,
            details={"current_hash": exc.current_hash},
        ) from exc
    except (FileNotFoundError, KeyError) as exc:
        raise ApiError(code="contract_not_found", message=str(exc).strip("'\""), status_code=404) from exc
    except FileExistsError as exc:
        raise ApiError(code="contract_exists", message=str(exc), status_code=409) from exc
    except (ContractParseError, ValueError, ValidationError) as exc:
        raise ApiError(code="contract_invalid", message=str(exc), status_code=400) from exc


@router.get("/formats")
def list_formats(request: Request) -> dict[str, Any]:
    return {"schema": "tags-machine-core.web.prompt-formats/v1", "formats": _service(request).formats()}


@router.get("/contracts/action-groups")
def list_action_groups(request: Request, q: str | None = None) -> dict[str, Any]:
    return {"groups": _service(request).action_groups(q)}


@router.get("/contracts/action-groups/detail")
def action_group_detail(ref: str, request: Request) -> dict[str, Any]:
    return _call(lambda: _service(request).action_group(ref))


@router.get("/contracts")
def list_contracts(
    request: Request,
    node: str | None = None,
    format: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    items = _service(request).list(node=node, status=status, target_format=format)
    return {"schema": "tags-machine-core.web.contract-list/v1", "contracts": items, "now": time.time()}


@router.get("/contracts/index")
def contracts_index(request: Request, since: float = 0) -> dict[str, Any]:
    """§5.5：只返回修改时间晚于 since 的契约；前端每 5 秒轮询一次。"""
    service = _service(request)
    now = time.time()
    return {"changed": service.store.changed_since(since), "ids": service.store.list_ids(), "now": now}


@router.post("/contracts/refresh")
def refresh_contracts(request: Request, pull: int = 0) -> dict[str, Any]:
    service = _service(request)
    report: dict[str, Any] | None = None
    if pull:
        from tags_machine_core.web.category_view import git_pull_ff_only

        report = git_pull_ff_only(service.sources.action_root)
    return {"pull": report, "contracts": service.list(), "now": time.time()}


@router.post("/contracts")
def create_contract(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    return _call(lambda: _service(request).create(payload))


@router.get("/contracts/{contract_id}")
def get_contract(contract_id: str, request: Request) -> dict[str, Any]:
    return _call(lambda: _service(request).detail(contract_id))


@router.get("/contracts/{contract_id}/prompt")
def contract_prompt(contract_id: str, request: Request, kind: str = "tools") -> dict[str, Any]:
    return _call(lambda: _service(request).prompt(contract_id, kind))


@router.post("/contracts/{contract_id}/import")
def import_contract_frames(contract_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    text = str(payload.get("text") or "")
    return _call(lambda: _service(request).import_frames(contract_id, text, expected_hash=payload.get("hash")))


@router.put("/contracts/{contract_id}/frames/{frame_id}")
def save_contract_frame(contract_id: str, frame_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    prompts = payload.get("prompts")
    expected = payload.get("hash")
    if not isinstance(prompts, dict) or not isinstance(expected, str):
        raise ApiError(code="contract_invalid", message="需要 prompts（对象）和 hash（文件 hash）", status_code=400)
    return _call(
        lambda: _service(request).save_frame(
            contract_id,
            frame_id,
            {str(key): str(value or "") for key, value in prompts.items()},
            expected_hash=expected,
        )
    )


@router.put("/contracts/{contract_id}/fields")
def set_contract_fields(contract_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    fields = {key: str(value) for key, value in (payload.get("fields") or {}).items()}
    return _call(lambda: _service(request).set_fields(contract_id, fields, expected_hash=payload.get("hash")))


@router.get("/contracts/{contract_id}/results")
def contract_results(contract_id: str, request: Request) -> dict[str, Any]:
    return _call(lambda: _service(request).results(contract_id))


@router.put("/contracts/{contract_id}/picks")
def update_contract_picks(contract_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    frame_id = str(payload.get("frame_id") or "").strip()
    if not frame_id:
        raise ApiError(code="contract_invalid", message="需要 frame_id", status_code=400)
    add = [str(item) for item in payload.get("add") or []]
    remove = [str(item) for item in payload.get("remove") or []]
    picks = _call(lambda: _service(request).update_picks(contract_id, frame_id, add=add, remove=remove))
    return {"id": contract_id, "picks": picks}
