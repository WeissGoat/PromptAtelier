from __future__ import annotations

import asyncio
import atexit
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 优先使用当前 refactor 仓库 vendored 的 ai-image-gateway，
# 避免本机其它同名开发包抢占导入顺序。
_VENDORED_GATEWAY_ROOT = Path(__file__).resolve().parents[3] / "vendor" / "ai-image-gateway"
if _VENDORED_GATEWAY_ROOT.exists():
    gateway_root_text = str(_VENDORED_GATEWAY_ROOT)
    if gateway_root_text not in sys.path:
        sys.path.insert(0, gateway_root_text)

from ai_image_gateway import NovelAIRawPayload
from ai_image_gateway.config import ProviderConfig
from ai_image_gateway.providers.novelai import NovelAIRawClient

from tags_machine_core.clients.novelai import NovelAIClient, NovelAIImage
from tags_machine_core.contracts import RenderRequest

import os


def sanitize_proxy_env() -> None:
    """Removes IPv6 entries (such as ::1) from NO_PROXY/no_proxy to avoid httpx InvalidURL crashes."""
    for key in ("NO_PROXY", "no_proxy"):
        val = os.environ.get(key)
        if val and "::" in val:
            cleaned = [p.strip() for p in val.split(",") if "::" not in p]
            os.environ[key] = ",".join(cleaned)


sanitize_proxy_env()


class _SharedTransport:
    """进程内共用的 NovelAI 连接。

    执行器每个任务都会新建 GatewayNovelAIRawClient；这里用一个后台线程常驻事件循环，
    同一组 token / 地址 / 超时只初始化一次 NovelAIRawClient，像旧链路一样一直复用 HTTPS 连接，
    而不是每张图重新握手。进程退出时统一关闭。
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._start_lock = threading.Lock()
        self._init_lock: asyncio.Lock | None = None
        self._clients: dict[tuple[Any, ...], NovelAIRawClient] = {}

    def run(self, key: tuple[Any, ...], config: ProviderConfig, payload: NovelAIRawPayload):
        future = asyncio.run_coroutine_threadsafe(self._generate(key, config, payload), self._ensure_loop())
        return future.result()

    def close(self) -> None:
        if self._loop is None or not self._clients:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._close_all(), self._loop).result(timeout=10)
        except Exception:
            pass

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, name="novelai-transport", daemon=True).start()
                self._loop = loop
                atexit.register(self.close)
            return self._loop

    async def _generate(self, key: tuple[Any, ...], config: ProviderConfig, payload: NovelAIRawPayload):
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            client = self._clients.get(key)
            if client is None:
                client = NovelAIRawClient(config)
                await client.initialize()
                self._clients[key] = client
        return await client.generate_raw(payload)

    async def _close_all(self) -> None:
        clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            await client.close()


_TRANSPORT = _SharedTransport()


@dataclass
class GatewayNovelAIRawClient:
    access_token: str
    base_url: str
    timeout: int = 120
    retry: int = 3
    retry_interval: float | None = None
    last_retry_records: list[dict[str, Any]] = field(default_factory=list)

    def build_payload(self, request: RenderRequest) -> dict[str, Any]:
        return NovelAIClient(access_token=self.access_token).build_payload(request)

    def generate_images(self, request: RenderRequest) -> list[NovelAIImage]:
        self.last_retry_records = []
        payload = NovelAIRawPayload.model_validate(self.build_payload(request))
        result = self._generate_raw(payload)
        self.last_retry_records = [
            record.model_dump(mode="json")
            for record in result.retry_records
        ]
        return [
            NovelAIImage(filename=image.filename, content=image.image_bytes)
            for image in result.images
        ]

    def _generate_raw(self, payload: NovelAIRawPayload):
        key = (self.access_token, self.base_url, self.timeout, self.retry, self.retry_interval)
        config = ProviderConfig(
            enabled=True,
            auth={"access_token": self.access_token},
            settings={
                "base_url": self.base_url,
                "timeout": self.timeout,
                "retry": self.retry,
                "retry_interval": self.retry_interval,
                # 请求头用 ai-image-gateway 的默认值（照官网前端），这里不再另给
            },
        )
        return _TRANSPORT.run(key, config, payload)
