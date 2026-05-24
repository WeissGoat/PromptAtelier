from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import requests

from tags_machine_core.contracts import RenderRequest
from tags_machine_core.json_tools import sanitize_json_for_display


COMFYUI_BASE_URL = "http://127.0.0.1:8188"


class ComfyUIClientError(RuntimeError):
    def __init__(self, status_code: int, response_text: str, sanitized_payload: dict[str, Any]):
        self.status_code = status_code
        self.response_text = response_text
        self.sanitized_payload = sanitized_payload
        super().__init__(
            f"ComfyUI request failed with HTTP {status_code}: {response_text[:300]}"
        )


@dataclass(frozen=True)
class ComfyUIPromptResult:
    prompt_id: str | None
    raw: dict[str, Any]


@dataclass
class ComfyUIClient:
    base_url: str = COMFYUI_BASE_URL
    timeout: int = 120
    http_client: Any | None = None

    def build_payload(self, request: RenderRequest, *, client_id: str | None = None) -> dict[str, Any]:
        workflow = self.build_workflow(request)
        payload: dict[str, Any] = {"prompt": workflow}
        if client_id:
            payload["client_id"] = client_id
        return payload

    def build_workflow(self, request: RenderRequest) -> dict[str, Any]:
        workflow = (
            request.params["workflow_json"]
            if "workflow_json" in request.params
            else request.params.get("workflow")
        )
        if not isinstance(workflow, dict):
            raise ValueError(
                "ComfyUIClient requires params.workflow_json or params.workflow to be a workflow mapping"
            )
        workflow = copy.deepcopy(workflow)
        for path, value in (request.params.get("node_overrides") or {}).items():
            self._set_workflow_value(workflow, str(path), value)
        return workflow

    def queue_prompt(
        self,
        request: RenderRequest,
        *,
        client_id: str | None = None,
    ) -> ComfyUIPromptResult:
        payload = self.build_payload(request, client_id=client_id)
        response = self._session().post(
            f"{self.base_url.rstrip('/')}/prompt",
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise ComfyUIClientError(
                status_code=response.status_code,
                response_text=response.text,
                sanitized_payload=sanitize_json_for_display(payload),
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            data = {"raw": data}
        prompt_id = data.get("prompt_id")
        return ComfyUIPromptResult(
            prompt_id=str(prompt_id) if prompt_id is not None else None,
            raw=data,
        )

    def _session(self):
        return self.http_client or requests

    def _set_workflow_value(self, workflow: dict[str, Any], path: str, value: Any) -> None:
        parts = [part for part in path.split(".") if part]
        if not parts:
            raise ValueError("node_overrides path cannot be empty")
        current: Any = workflow
        for part in parts[:-1]:
            if not isinstance(current, dict):
                raise ValueError(f"Cannot apply node override through non-mapping path: {path}")
            current = current.setdefault(part, {})
        if not isinstance(current, dict):
            raise ValueError(f"Cannot apply node override to non-mapping path: {path}")
        current[parts[-1]] = value
