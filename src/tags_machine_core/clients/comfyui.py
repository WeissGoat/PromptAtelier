from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
import mimetypes
from pathlib import Path
import time
from typing import Any, Protocol
from urllib.parse import urlencode

import requests

from tags_machine_core.contracts import RenderRequest
from tags_machine_core.json_tools import sanitize_json_for_display
from tags_machine_core.logging_config import get_logger
from tags_machine_core.renderers.comfyui_workflow import (
    WorkflowPathStyle,
    apply_node_overrides,
    normalize_workflow_file_paths,
    output_node_ids,
    prune_workflow_to_outputs,
)


COMFYUI_BASE_URL = "http://127.0.0.1:8188"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
logger = get_logger(__name__)


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


@dataclass(frozen=True)
class ComfyUIInputFile:
    name: str
    content: bytes
    subfolder: str = ""


@dataclass(frozen=True)
class PreparedComfyUIWorkflow:
    """与平台无关的待提交 workflow：已套用参数、按 output_nodes 裁剪、按目标平台归一化路径。"""

    prompt: dict[str, Any]
    output_nodes: tuple[str, ...] = ()
    extra_data: dict[str, Any] = field(default_factory=dict)
    input_files: tuple[ComfyUIInputFile, ...] = ()
    pruned_node_ids: tuple[str, ...] = ()
    normalized_paths: tuple[str, ...] = ()

    def summary(self) -> dict[str, Any]:
        return {
            "node_count": len(self.prompt),
            "output_nodes": list(self.output_nodes),
            "pruned_node_count": len(self.pruned_node_ids),
            "normalized_paths": list(self.normalized_paths),
            "input_files": [
                f"{item.subfolder}/{item.name}" if item.subfolder else item.name
                for item in self.input_files
            ],
        }


def prepare_comfyui_workflow(
    request: RenderRequest,
    *,
    prune_to_output_nodes: bool = True,
    path_style: WorkflowPathStyle = "native",
) -> PreparedComfyUIWorkflow:
    params = request.params
    workflow = params["workflow_json"] if "workflow_json" in params else params.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError(
            "ComfyUIClient requires params.workflow_json or params.workflow to be a workflow mapping"
        )
    workflow = copy.deepcopy(workflow)
    apply_node_overrides(workflow, params.get("node_overrides") or {})
    output_nodes = tuple(output_node_ids({"output_nodes": params.get("output_nodes")}))
    pruned: list[str] = []
    if prune_to_output_nodes and output_nodes:
        workflow, pruned = prune_workflow_to_outputs(workflow, output_nodes)
    normalized = normalize_workflow_file_paths(workflow, path_style)
    extra_data: dict[str, Any] = {}
    extra_pnginfo = params.get("extra_pnginfo")
    if isinstance(extra_pnginfo, dict) and extra_pnginfo:
        extra_data["extra_pnginfo"] = copy.deepcopy(extra_pnginfo)
    return PreparedComfyUIWorkflow(
        prompt=workflow,
        output_nodes=output_nodes,
        extra_data=extra_data,
        input_files=load_comfyui_input_files(params.get("input_files")),
        pruned_node_ids=tuple(pruned),
        normalized_paths=tuple(normalized),
    )


def load_comfyui_input_files(value: Any) -> tuple[ComfyUIInputFile, ...]:
    if not value:
        return ()
    if not isinstance(value, list):
        raise ValueError("ComfyUI params.input_files must be a list")
    files: list[ComfyUIInputFile] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not item.get("path"):
            raise ValueError(f"ComfyUI params.input_files[{index}] requires a path")
        source = Path(str(item["path"]))
        name = str(item.get("name") or source.name)
        subfolder = str(item.get("subfolder") or "").strip("/\\")
        if "/" in name or "\\" in name:
            raise ValueError(f"ComfyUI input file name must be a plain filename: {name!r}")
        if (subfolder, name) in seen:
            raise ValueError(f"Duplicate ComfyUI input file: {name!r} in subfolder {subfolder!r}")
        seen.add((subfolder, name))
        files.append(ComfyUIInputFile(name=name, content=source.read_bytes(), subfolder=subfolder))
    return tuple(files)


class ComfyUITransport(Protocol):
    """把准备好的 workflow 交给某个 ComfyUI 宿主执行。

    native 由 ComfyUIClient 实现（ComfyUI 原生 HTTP：本地、云主机、Modal web_server）。
    serverless 任务队列类平台（提交 workflow → 轮询 job → 取图）以后按这个接口写 adapter，
    准备阶段统一复用 prepare_comfyui_workflow。
    """

    def prepare(self, request: RenderRequest) -> PreparedComfyUIWorkflow: ...

    def payload(
        self,
        prepared: PreparedComfyUIWorkflow,
        *,
        client_id: str | None = None,
    ) -> dict[str, Any]: ...

    def queue(
        self,
        prepared: PreparedComfyUIWorkflow,
        *,
        client_id: str | None = None,
    ) -> ComfyUIPromptResult: ...

    def run(
        self,
        prepared: PreparedComfyUIWorkflow,
        *,
        client_id: str | None = None,
        poll_interval: float = 1.0,
        max_wait_seconds: float | None = None,
    ) -> ComfyUIGenerationResult: ...


@dataclass
class ComfyUIClient:
    """ComfyUI 原生 HTTP 协议：POST /prompt → 轮询 /history → GET /view。"""

    base_url: str = COMFYUI_BASE_URL
    timeout: int = 120
    retry: int = 3
    retry_interval: float = 2.0
    http_client: Any | None = None
    headers: dict[str, str] = field(default_factory=dict)
    prune_to_output_nodes: bool = True
    path_style: WorkflowPathStyle = "native"
    ready_timeout: float = 0.0
    _ready: bool = field(default=False, init=False, repr=False)

    def prepare(self, request: RenderRequest) -> PreparedComfyUIWorkflow:
        return prepare_comfyui_workflow(
            request,
            prune_to_output_nodes=self.prune_to_output_nodes,
            path_style=self.path_style,
        )

    def payload(
        self,
        prepared: PreparedComfyUIWorkflow,
        *,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt": copy.deepcopy(prepared.prompt)}
        if prepared.extra_data:
            payload["extra_data"] = copy.deepcopy(prepared.extra_data)
        if client_id:
            payload["client_id"] = client_id
        return payload

    def queue(
        self,
        prepared: PreparedComfyUIWorkflow,
        *,
        client_id: str | None = None,
    ) -> ComfyUIPromptResult:
        self.ensure_ready()
        self.upload_input_files(prepared)
        payload = self.payload(prepared, client_id=client_id)
        response = self._request("post", self._url("/prompt"), json=payload, timeout=self.timeout)
        if response.status_code >= 400:
            raise ComfyUIClientError(
                status_code=response.status_code,
                response_text=self._error_text(response),
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

    def run(
        self,
        prepared: PreparedComfyUIWorkflow,
        *,
        client_id: str | None = None,
        poll_interval: float = 1.0,
        max_wait_seconds: float | None = None,
    ) -> ComfyUIGenerationResult:
        queued = self.queue(prepared, client_id=client_id)
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
            images=self.download_history_images(
                history,
                prompt_id=queued.prompt_id,
                output_nodes=prepared.output_nodes,
            ),
        )

    def build_workflow(self, request: RenderRequest) -> dict[str, Any]:
        return self.prepare(request).prompt

    def build_payload(self, request: RenderRequest, *, client_id: str | None = None) -> dict[str, Any]:
        return self.payload(self.prepare(request), client_id=client_id)

    def queue_prompt(
        self,
        request: RenderRequest,
        *,
        client_id: str | None = None,
    ) -> ComfyUIPromptResult:
        return self.queue(self.prepare(request), client_id=client_id)

    def generate_images(
        self,
        request: RenderRequest,
        *,
        client_id: str | None = None,
        poll_interval: float = 1.0,
        max_wait_seconds: float | None = None,
    ) -> ComfyUIGenerationResult:
        return self.run(
            self.prepare(request),
            client_id=client_id,
            poll_interval=poll_interval,
            max_wait_seconds=max_wait_seconds,
        )

    def ensure_ready(self) -> None:
        if self._ready or self.ready_timeout <= 0:
            return
        self.wait_until_ready(self.ready_timeout)
        self._ready = True

    def wait_until_ready(self, max_wait_seconds: float) -> dict[str, Any]:
        """轮询 /system_stats，等 serverless 冷启动的 ComfyUI 能接请求。"""
        started_at = time.monotonic()
        delay = 2.0
        last_error = "no response"
        while True:
            remaining = max_wait_seconds - (time.monotonic() - started_at)
            try:
                response = self._send(
                    "get",
                    self._url("/system_stats"),
                    timeout=max(1.0, min(float(self.timeout), remaining)),
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 400:
                    data = _json_or_none(response)
                    return data if isinstance(data, dict) else {}
                if response.status_code in {401, 403}:
                    raise ComfyUIClientError(
                        status_code=response.status_code,
                        response_text=(
                            "ComfyUI target rejected the credentials; check comfyui auth: "
                            + self._error_text(response)
                        ),
                        sanitized_payload={"endpoint": "system_stats"},
                    )
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    raise ComfyUIClientError(
                        status_code=response.status_code,
                        response_text=self._error_text(response),
                        sanitized_payload={"endpoint": "system_stats"},
                    )
                last_error = f"HTTP {response.status_code}"
            elapsed = time.monotonic() - started_at
            if elapsed >= max_wait_seconds:
                raise TimeoutError(
                    f"ComfyUI at {self.base_url} was not ready after "
                    f"{max_wait_seconds:.0f}s; last error: {last_error}"
                )
            logger.info(
                "waiting for ComfyUI url=%s elapsed=%.0fs last_error=%s",
                self.base_url,
                elapsed,
                last_error,
            )
            time.sleep(min(delay, max(0.0, max_wait_seconds - elapsed)))
            delay = min(delay * 1.5, 15.0)

    def upload_input_files(self, prepared: PreparedComfyUIWorkflow) -> list[dict[str, Any]]:
        uploaded: list[dict[str, Any]] = []
        for item in prepared.input_files:
            mime_type = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
            sanitized = {"endpoint": "upload/image", "name": item.name, "subfolder": item.subfolder}
            response = self._request(
                "post",
                self._url("/upload/image"),
                files={"image": (item.name, item.content, mime_type)},
                data={"type": "input", "subfolder": item.subfolder, "overwrite": "true"},
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                raise ComfyUIClientError(
                    status_code=response.status_code,
                    response_text=self._error_text(response),
                    sanitized_payload=sanitized,
                )
            data = _json_or_none(response)
            stored = data if isinstance(data, dict) else {}
            if stored.get("name") != item.name or str(stored.get("subfolder") or "") != item.subfolder:
                raise ComfyUIClientError(
                    status_code=response.status_code,
                    response_text=f"ComfyUI stored the input file as {stored!r}",
                    sanitized_payload=sanitized,
                )
            uploaded.append(stored)
        return uploaded

    def get_history(self, prompt_id: str) -> dict[str, Any]:
        response = self._request(
            "get",
            self._url(f"/history/{prompt_id}"),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise ComfyUIClientError(
                status_code=response.status_code,
                response_text=self._error_text(response),
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
            if entry is not None:
                if self._history_failed(entry):
                    raise ComfyUIClientError(
                        status_code=200,
                        response_text=self._history_failure_text(prompt_id, entry),
                        sanitized_payload={
                            "prompt_id": prompt_id,
                            "status": entry.get("status"),
                            "history": sanitize_json_for_display(history),
                        },
                    )
                if self._history_has_images(entry) or self._history_completed(entry):
                    return history
            if time.monotonic() - started_at >= max_wait:
                raise TimeoutError(f"Timed out waiting for ComfyUI prompt: {prompt_id}")
            time.sleep(poll_interval)

    def download_history_images(
        self,
        history: dict[str, Any],
        *,
        prompt_id: str | None = None,
        output_nodes: list[str] | tuple[str, ...] | None = None,
    ) -> list[ComfyUIImage]:
        entry = self._history_entry(history, prompt_id)
        if entry is None:
            return []
        outputs = entry.get("outputs") if isinstance(entry, dict) else {}
        if not isinstance(outputs, dict):
            return []

        images: list[ComfyUIImage] = []
        allowed_nodes = {str(item) for item in (output_nodes or []) if str(item)}
        for node_id, output in outputs.items():
            if allowed_nodes and str(node_id) not in allowed_nodes:
                continue
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
        response = self._request(
            "get",
            self._url(f"/view?{query}"),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise ComfyUIClientError(
                status_code=response.status_code,
                response_text=self._error_text(response),
                sanitized_payload={
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": image_type,
                },
            )
        response.raise_for_status()
        return response.content

    def object_info(self) -> dict[str, Any]:
        self.ensure_ready()
        response = self._request(
            "get",
            self._url("/object_info"),
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise ComfyUIClientError(
                status_code=response.status_code,
                response_text=self._error_text(response),
                sanitized_payload={"endpoint": "object_info"},
            )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"raw": data}

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _session(self):
        return self.http_client or requests

    def _send(self, method: str, url: str, **kwargs):
        if self.headers:
            kwargs["headers"] = {**self.headers, **(kwargs.get("headers") or {})}
        return getattr(self._session(), method)(url, **kwargs)

    def _request(self, method: str, url: str, **kwargs):
        attempts = max(1, int(self.retry or 1))
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self._send(method, url, **kwargs)
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < attempts:
                    time.sleep(max(0.0, float(self.retry_interval or 0.0)))
                    continue
                return response
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt >= attempts:
                    raise
                time.sleep(max(0.0, float(self.retry_interval or 0.0)))
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"ComfyUI request did not return a response: {method} {url}")

    def _error_text(self, response: Any) -> str:
        text = str(getattr(response, "text", "") or "")
        try:
            data = response.json()
        except Exception:
            return text
        if not isinstance(data, dict):
            return text
        parts = [text] if text else []
        error = data.get("error")
        node_errors = data.get("node_errors")
        if error:
            parts.append("error=" + json_like(error))
        if node_errors:
            parts.append("node_errors=" + json_like(node_errors))
        return "; ".join(parts) or json_like(data)

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

    def _history_completed(self, entry: dict[str, Any]) -> bool:
        status = entry.get("status")
        if not isinstance(status, dict):
            return False
        return status.get("completed") is True or self._status_text(status) == "success"

    def _history_failed(self, entry: dict[str, Any]) -> bool:
        status = entry.get("status")
        if not isinstance(status, dict):
            return False
        return self._status_text(status) in {"error", "failed"}

    def _history_failure_text(self, prompt_id: str, entry: dict[str, Any]) -> str:
        status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
        messages = entry.get("messages")
        error = entry.get("error")
        return (
            f"ComfyUI prompt failed: {prompt_id}; "
            f"status={status}; error={error}; messages={messages}"
        )

    def _status_text(self, status: dict[str, Any]) -> str:
        return str(status.get("status_str") or status.get("status") or "").lower()


def _json_or_none(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def json_like(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:2000]
    except TypeError:
        return str(value)[:2000]
