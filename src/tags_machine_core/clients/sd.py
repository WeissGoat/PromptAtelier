from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import requests

from tags_machine_core.contracts import RenderRequest
from tags_machine_core.json_tools import sanitize_json_for_display


SD_WEBUI_BASE_URL = "http://127.0.0.1:7860"


class SDClientError(RuntimeError):
    def __init__(self, status_code: int, response_text: str, sanitized_payload: dict[str, Any]):
        self.status_code = status_code
        self.response_text = response_text
        self.sanitized_payload = sanitized_payload
        super().__init__(f"SD request failed with HTTP {status_code}: {response_text[:300]}")


@dataclass(frozen=True)
class SDImage:
    filename: str
    content: bytes


@dataclass
class SDClient:
    base_url: str = SD_WEBUI_BASE_URL
    timeout: int = 120
    http_client: Any | None = None

    def build_payload(self, request: RenderRequest) -> dict[str, Any]:
        params = request.params
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "seed": request.seed if request.seed is not None else params.get("seed", -1),
            "width": request.size.width,
            "height": request.size.height,
            "steps": params.get("steps", 28),
            "cfg_scale": params.get("cfg_scale", params.get("cfg", 7.0)),
            "sampler_name": params.get("sampler", "Euler a"),
            "batch_size": params.get("batch_size", 1),
            "n_iter": params.get("n_iter", 1),
        }
        scheduler = params.get("scheduler")
        if scheduler:
            payload["scheduler"] = scheduler

        override_settings = self._override_settings(params)
        if override_settings:
            payload["override_settings"] = override_settings

        hires_fix = params.get("hires_fix")
        if isinstance(hires_fix, dict) and hires_fix.get("enabled"):
            payload.update(self._hires_payload(hires_fix))

        controlnet = params.get("controlnet")
        if controlnet:
            payload["alwayson_scripts"] = {"controlnet": {"args": controlnet}}

        extra_payload = params.get("extra_payload")
        if isinstance(extra_payload, dict):
            payload.update(extra_payload)
        return payload

    def txt2img(self, request: RenderRequest) -> dict[str, Any]:
        payload = self.build_payload(request)
        response = self._session().post(
            f"{self.base_url.rstrip('/')}/sdapi/v1/txt2img",
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SDClientError(
                status_code=response.status_code,
                response_text=response.text,
                sanitized_payload=sanitize_json_for_display(payload),
            )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"raw": data}

    def generate_images(self, request: RenderRequest) -> list[SDImage]:
        data = self.txt2img(request)
        images = data.get("images") or []
        result: list[SDImage] = []
        for index, image in enumerate(images, start=1):
            if not isinstance(image, str):
                continue
            result.append(
                SDImage(
                    filename=f"sd_{request.seed if request.seed is not None else 0}_{index:02d}.png",
                    content=_decode_base64_image(image),
                )
            )
        return result

    def _session(self):
        return self.http_client or requests

    def _override_settings(self, params: dict[str, Any]) -> dict[str, Any]:
        settings: dict[str, Any] = {}
        checkpoint = params.get("checkpoint") or params.get("model")
        if checkpoint:
            settings["sd_model_checkpoint"] = checkpoint
        if params.get("vae"):
            settings["sd_vae"] = params["vae"]
        if params.get("clip_skip"):
            settings["CLIP_stop_at_last_layers"] = params["clip_skip"]
        return settings

    def _hires_payload(self, hires_fix: dict[str, Any]) -> dict[str, Any]:
        payload = {"enable_hr": True}
        for source_key, target_key in {
            "scale": "hr_scale",
            "upscaler": "hr_upscaler",
            "steps": "hr_second_pass_steps",
            "denoising_strength": "denoising_strength",
        }.items():
            if source_key in hires_fix:
                payload[target_key] = hires_fix[source_key]
        return payload


def _decode_base64_image(value: str) -> bytes:
    if "," in value and value.strip().lower().startswith("data:"):
        value = value.split(",", 1)[1]
    return base64.b64decode(value)
