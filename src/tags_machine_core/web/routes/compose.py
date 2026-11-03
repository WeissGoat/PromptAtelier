from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError

from tags_machine_core.prompt_tokens import render_request_token_usage
from tags_machine_core.web.errors import ApiError

router = APIRouter()


@router.post("/compose-preview")
def compose_preview(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    api = request.app.state.generation_api
    try:
        _validate_prompt_policy_override(payload)
        result = api.resolve_compose_render_plan(payload)
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        raise ApiError(
            code="compose_preview_failed",
            message=str(exc),
            status_code=400,
        ) from exc
    render_request = result.get("render_request")
    if result.get("status") == "ready" and isinstance(render_request, dict):
        # 最终提示词（含画风前后缀、分角色提示词）按官网规则数 token；只有 NovelAI 有。
        usage = render_request_token_usage(render_request)
        if usage is not None:
            result["token_usage"] = usage
    return result


def _validate_prompt_policy_override(payload: dict[str, Any]) -> None:
    compose = payload.get("compose") or payload
    if not isinstance(compose, dict):
        return
    prompt_policy = compose.get("prompt_policy")
    if isinstance(prompt_policy, dict) and prompt_policy.get("require") is not None:
        raise ValueError("Web prompt_policy cannot override require; configure the project baseline instead")
