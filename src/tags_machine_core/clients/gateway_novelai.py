from __future__ import annotations

import asyncio
import sys
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
        result = asyncio.run(self._generate_raw(payload))
        self.last_retry_records = [
            record.model_dump(mode="json")
            for record in result.retry_records
        ]
        return [
            NovelAIImage(filename=image.filename, content=image.image_bytes)
            for image in result.images
        ]

    async def _generate_raw(self, payload: NovelAIRawPayload):
        client = NovelAIRawClient(
            ProviderConfig(
                enabled=True,
                auth={"access_token": self.access_token},
                settings={
                    "base_url": self.base_url,
                    "timeout": self.timeout,
                    "retry": self.retry,
                    "retry_interval": self.retry_interval,
                },
            )
        )
        await client.initialize()
        try:
            return await client.generate_raw(payload)
        finally:
            await client.close()
