"""ComfyUI 运行位置的在线状态，给 Web 显示用。查询本身不能把 serverless 容器拉起来。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests

from tags_machine_core.config import ResolvedComfyUITarget


LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_modal_functions: dict[tuple[str, str], Any] = {}


def is_local_target(target: ResolvedComfyUITarget) -> bool:
    host = (urlparse(target.base_url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost")


def probe_target_status(
    target: ResolvedComfyUITarget,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 1.5,
) -> dict[str, Any]:
    kind = target.status_probe.type
    if kind == "auto":
        kind = "http" if is_local_target(target) else "none"
    if kind == "http":
        return _probe_http(target, headers or {}, timeout)
    if kind == "modal":
        return _probe_modal(target.status_probe.app, target.status_probe.function)
    return {"state": "unknown"}


def _probe_http(
    target: ResolvedComfyUITarget,
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{target.base_url.rstrip('/')}/system_stats", headers=headers, timeout=timeout
        )
    except requests.RequestException:
        return {"state": "offline"}
    return {"state": "online" if response.status_code < 400 else "offline"}


def _probe_modal(app: str | None, function: str | None) -> dict[str, Any]:
    """读 Modal 函数当前的容器数：只是一次 API 查询，不会启动容器。"""
    if not app or not function:
        return {"state": "unknown", "detail": "status_probe type modal needs app and function"}
    try:
        import modal
    except ImportError:
        return {"state": "unknown", "detail": "modal SDK is not installed in this environment"}
    try:
        handle = _modal_functions.get((app, function))
        if handle is None:
            handle = modal.Function.from_name(app, function)
            _modal_functions[(app, function)] = handle
        stats = handle.get_current_stats()
    except Exception as exc:  # noqa: BLE001 - 状态查询失败只影响显示
        return {"state": "unknown", "detail": f"{type(exc).__name__}: {exc}"[:200]}
    containers = int(getattr(stats, "num_total_runners", 0) or 0)
    return {
        "state": "running" if containers else "stopped",
        "containers": containers,
        "active_requests": int(getattr(stats, "num_running_inputs", 0) or 0),
    }
