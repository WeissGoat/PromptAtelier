from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter, Retry

from tags_machine_core.contracts import RenderRequest
from tags_machine_core.json_tools import sanitize_json_for_display


IMAGE_BASE_URL = "https://image.novelai.net"


class NovelAIClientError(RuntimeError):
    def __init__(self, status_code: int, response_text: str, sanitized_payload: dict[str, Any]):
        self.status_code = status_code
        self.response_text = response_text
        self.sanitized_payload = sanitized_payload
        super().__init__(
            f"NovelAI request failed with HTTP {status_code}: {response_text[:300]}"
        )


@dataclass(frozen=True)
class NovelAIImage:
    filename: str
    content: bytes


@dataclass
class NovelAIClient:
    access_token: str
    base_url: str = IMAGE_BASE_URL
    timeout: int = 120
    retry: int = 3
    http_client: Any | None = None

    def build_payload(self, request: RenderRequest) -> dict[str, Any]:
        return {
            "input": request.prompt,
            "model": request.model,
            "action": request.meta.get("action", "generate"),
            "parameters": request.params,
        }

    def generate_image_zip(self, request: RenderRequest) -> bytes:
        session = self._session()
        payload = self.build_payload(request)
        response = session.post(
            f"{self.base_url}/ai/generate-image",
            json=payload,
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            # 失败时保留足够调试信息，但不要把图片 base64 原样塞进异常/日志。
            raise NovelAIClientError(
                status_code=response.status_code,
                response_text=response.text,
                sanitized_payload=sanitize_json_for_display(payload),
            )
        response.raise_for_status()
        return response.content

    def generate_images(self, request: RenderRequest) -> list[NovelAIImage]:
        zipped_bytes = self.generate_image_zip(request)
        with zipfile.ZipFile(io.BytesIO(zipped_bytes)) as zipped:
            return [
                NovelAIImage(filename=info.filename, content=zipped.read(info))
                for info in zipped.infolist()
                if not info.is_dir()
            ]

    def generate_image_bytes(self, request: RenderRequest) -> list[bytes]:
        return [image.content for image in self.generate_images(request)]

    def _session(self):
        if self.http_client is not None:
            return self.http_client
        # 只对网络抖动和限流做有限重试，业务错误直接抛出。
        if self.retry <= 1:
            return requests
        retries = Retry(
            total=self.retry,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        session = requests.Session()
        session.mount("https://", HTTPAdapter(max_retries=retries))
        return session
