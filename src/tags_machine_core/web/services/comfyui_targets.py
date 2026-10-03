from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading
import time
from typing import Any

from tags_machine_core.comfyui_status import is_local_target, probe_target_status
from tags_machine_core.config import ComfyUIConfig, ResolvedComfyUITarget
from tags_machine_core.execution import comfyui_auth_headers


class ComfyUITargetService:
    """Web 的运行位置列表和状态。

    状态缓存几秒，避免多个面板同时轮询时反复查询；Web 自己发起的生成会记录
    进行中的任务数和最后使用时间，用来估算云端还有多久自动关机。
    """

    def __init__(
        self,
        config: ComfyUIConfig,
        *,
        probe: Callable[..., dict[str, Any]] = probe_target_status,
        clock: Callable[[], float] = time.time,
        cache_seconds: float = 5.0,
    ):
        self.config = config
        self._probe = probe
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._last_used: dict[str, float] = {}
        self._active_jobs: dict[str, int] = {}

    def describe(self) -> dict[str, Any]:
        try:
            default_target: str | None = self.config.resolve_target().name
        except ValueError:
            default_target = None
        targets = [self.config.resolve_target(name) for name in self.config.target_names()]
        # 本机探测连不上时要等超时，云端查询也有网络延迟，各目标并行查。
        with ThreadPoolExecutor(max_workers=max(1, len(targets))) as pool:
            described = list(pool.map(self._describe, targets))
        return {
            "schema": "tags-machine-core.web.comfyui-targets/v1",
            "default_target": default_target,
            "targets": described,
        }

    @contextmanager
    def track(self, target: str | None) -> Iterator[None]:
        name = self._target_name(target)
        if name is None:
            yield
            return
        with self._lock:
            self._active_jobs[name] = self._active_jobs.get(name, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                self._active_jobs[name] -= 1
                self._last_used[name] = self._clock()
                self._cache.pop(name, None)

    def _target_name(self, target: str | None) -> str | None:
        try:
            return self.config.resolve_target(target).name
        except ValueError:
            return None

    def _describe(self, target: ResolvedComfyUITarget) -> dict[str, Any]:
        now = self._clock()
        status = dict(self._status(target, now))
        with self._lock:
            last_used = self._last_used.get(target.name)
            active_jobs = self._active_jobs.get(target.name, 0)
        idle_seconds = target.status_probe.idle_shutdown_seconds
        if status.get("state") == "running" and idle_seconds and last_used and not active_jobs:
            status["shutdown_in_seconds"] = max(0, round(last_used + idle_seconds - now))
        return {
            "name": target.name,
            "label": target.label or target.name,
            "location": "local" if is_local_target(target) else "cloud",
            "base_url": target.base_url,
            "status": status,
            "active_jobs": active_jobs,
            "last_used_at": last_used,
        }

    def _status(self, target: ResolvedComfyUITarget, now: float) -> dict[str, Any]:
        with self._lock:
            cached = self._cache.get(target.name)
        if cached and now - cached[0] < self._cache_seconds:
            return cached[1]
        try:
            headers = comfyui_auth_headers(target)
        except RuntimeError:
            headers = {}
        status = self._probe(target, headers=headers)
        with self._lock:
            self._cache[target.name] = (now, status)
        return status
