from __future__ import annotations

import copy
from dataclasses import dataclass
import time
from typing import Any
from urllib.parse import urlencode

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


@dataclass(frozen=True)
class ComfyUIImage:
    filename: str
    content: bytes
    subfolder: str = ""
    image_type: str = "output"
    node_id: str | None = None


@dataclass(frozen=True)
class ComfyUIGenerationResult:
    prompt_id: str | None
    queue_raw: dict[str, Any]
    history: dict[str, Any]
    images: list[ComfyUIImage]


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

    def generate_images(
        self,
        request: RenderRequest,
        *,
        client_id: str | None = None,
        poll_interval: float = 1.0,
        max_wait_seconds: float | None = None,
    ) -> ComfyUIGenerationResult:
        queued = self.queue_prompt(request, client_id=client_id)
        if not queued.prompt_id:
            raise ComfyUIClientError(
                status_code=200,
                response_text="ComfyUI response did not include prompt_id",
                sanitized_payload=sanitize_json_for_display(queued.raw),
            )
        history = self.wait_for_history(
            queued.prompt_id,
            poll_interval=poll_interval,
            max_wait_seconds=max_wait_seconds,
        )
        return ComfyUIGenerationResult(
            prompt_id=queued.prompt_id,
            queue_raw=queued.raw,
            history=history,
            images=self.download_history_images(history, prompt_id=queued.prompt_id),
        )

    def get_history(self, prompt_id: str) -> dict[str, Any]:
        response = self._session().get(
            f"{self.base_url.rstrip('/')}/history/{prompt_id}",
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise ComfyUIClientError(
                status_code=response.status_code,
                response_text=response.text,
                sanitized_payload={"prompt_id": prompt_id},
            )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"raw": data}

    def wait_for_history(
        self,
        prompt_id: str,
        *,
        poll_interval: float = 1.0,
        max_wait_seconds: float | None = None,
    ) -> dict[str, Any]:
        max_wait = self.timeout if max_wait_seconds is None else max_wait_seconds
        started_at = time.monotonic()
        while True:
            history = self.get_history(prompt_id)
            entry = self._history_entry(history, prompt_id)
            if entry is not None and (
                self._history_has_images(entry) or self._history_is_terminal(entry)
            ):
                return history
            if time.monotonic() - started_at >= max_wait:
                raise TimeoutError(f"Timed out waiting for ComfyUI prompt: {prompt_id}")
            time.sleep(poll_interval)

    def download_history_images(
        self,
        history: dict[str, Any],
        *,
        prompt_id: str | None = None,
    ) -> list[ComfyUIImage]:
        entry = self._history_entry(history, prompt_id)
        if entry is None:
            return []
        outputs = entry.get("outputs") if isinstance(entry, dict) else {}
        if not isinstance(outputs, dict):
            return []

        images: list[ComfyUIImage] = []
        for node_id, output in outputs.items():
            if not isinstance(output, dict):
                continue
            for image in output.get("images") or []:
                if not isinstance(image, dict):
                    continue
                filename = str(image.get("filename") or "")
                if not filename:
                    continue
                subfolder = str(image.get("subfolder") or "")
                image_type = str(image.get("type") or "output")
                images.append(
                    ComfyUIImage(
                        filename=filename,
                        content=self.download_image(
                            filename=filename,
                            subfolder=subfolder,
                            image_type=image_type,
                        ),
                        subfolder=subfolder,
                        image_type=image_type,
                        node_id=str(node_id),
                    )
                )
        return images

    def download_image(
        self,
        *,
        filename: str,
        subfolder: str = "",
        image_type: str = "output",
    ) -> bytes:
        query = urlencode(
            {
                "filename": filename,
                "subfolder": subfolder,
                "type": image_type,
            }
        )
        response = self._session().get(
            f"{self.base_url.rstrip('/')}/view?{query}",
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise ComfyUIClientError(
                status_code=response.status_code,
                response_text=response.text,
                sanitized_payload={
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": image_type,
                },
            )
        response.raise_for_status()
        return response.content

    def _session(self):
        return self.http_client or requests

    def _history_entry(
        self,
        history: dict[str, Any],
        prompt_id: str | None,
    ) -> dict[str, Any] | None:
        if prompt_id and isinstance(history.get(prompt_id), dict):
            return history[prompt_id]
        if prompt_id is None and "outputs" in history:
            return history
        if len(history) == 1:
            only_value = next(iter(history.values()))
            if isinstance(only_value, dict):
                return only_value
        return None

    def _history_has_images(self, entry: dict[str, Any]) -> bool:
        outputs = entry.get("outputs")
        if not isinstance(outputs, dict):
            return False
        for output in outputs.values():
            if isinstance(output, dict) and output.get("images"):
                return True
        return False

    def _history_is_terminal(self, entry: dict[str, Any]) -> bool:
        status = entry.get("status")
        if not isinstance(status, dict):
            return False
        if status.get("completed") is True:
            return True
        return str(status.get("status_str") or "").lower() in {"success", "error", "failed"}

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
