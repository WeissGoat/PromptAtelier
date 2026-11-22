"""Agent CLI 到本项目后台 API 的轻量客户端；不需要操作浏览器。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


def server_url(value: str | None) -> str:
    url = value or os.environ.get("PROMPTATELIER_URL")
    if not url:
        try:
            state = json.loads(Path("runtime/dev_web.json").read_text(encoding="utf-8"))
            port = int(state["backend_port"])
        except (OSError, ValueError, KeyError, TypeError):
            port = 53211
        url = f"http://127.0.0.1:{port}"
    return url.rstrip("/").removesuffix("/api") + "/api"


class GenerationClient:
    def __init__(self, server: str | None = None):
        self.url = server_url(server)
        self.session = requests.Session()
        self.session.trust_env = False

    def request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            response = self.session.request(method, self.url + path, timeout=60, **kwargs)
            data = response.json()
            if not response.ok:
                raise ValueError(
                    f"HTTP {response.status_code}: {json.dumps(data, ensure_ascii=False)}"
                )
            return data
        except requests.RequestException as exc:
            raise ValueError(
                f"无法连接 PromptAtelier 后台 {self.url}；请启动后台或用 --server 指定：{exc}"
            ) from exc

    def generate(self, contract_id: str, payload: dict) -> dict:
        return self.request(
            "POST", f"/contracts/{quote(contract_id, safe='')}/generate", json=payload
        )

    def job(self, job_id: str, *, wait: bool = False, timeout: float = 600) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            result = self.request("GET", f"/jobs/{quote(job_id, safe='')}")
            if not wait or result["status"] not in {"queued", "running", "cancelling"}:
                return result
            if time.monotonic() >= deadline:
                return {**result, "wait_timed_out": True}
            time.sleep(min(1, max(0, deadline - time.monotonic())))
