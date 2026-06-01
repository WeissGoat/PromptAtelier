from __future__ import annotations

import copy
from typing import Any

from tags_machine_core.contracts import PromptBundle, RenderRequest, RenderSize
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.renderers.common import (
    preserve_extra_params,
    render_meta,
    renderer_artist_payload,
)


class SDRenderAdapter:
    """把 PromptBundle 转成 Stable Diffusion dry-run 请求计划，不负责联网。"""

    backend = "sd"

    def build_request(
        self,
        bundle: PromptBundle,
        seed: int | None = None,
        width: int = 1024,
        height: int = 1024,
        model: str | None = None,
        action: str = "render-plan",
        params: dict[str, Any] | None = None,
        artist: NodeDocument | dict[str, Any] | None = None,
    ) -> RenderRequest:
        artist_payload = renderer_artist_payload(artist, self.backend)
        artist_params = copy.deepcopy(artist_payload.get("params", {}) or {})
        final_params = self._build_parameters(
            bundle=bundle,
            seed=seed,
            width=width,
            height=height,
            model=model,
            artist_payload=artist_payload,
            params={**artist_params, **(params or {})},
        )
        return RenderRequest(
            backend=self.backend,
            prompt=bundle.prompt.positive,
            negative_prompt=bundle.prompt.negative,
            model=final_params.get("checkpoint"),
            seed=final_params["seed"],
            size=RenderSize(width=width, height=height),
            params=final_params,
            artist_payload=artist_payload,
            meta=render_meta(bundle, action=action, backend=self.backend),
        )

    def _build_parameters(
        self,
        *,
        bundle: PromptBundle,
        seed: int | None,
        width: int,
        height: int,
        model: str | None,
        artist_payload: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        checkpoint = (
            model
            or params.get("checkpoint")
            or params.get("model")
            or artist_payload.get("checkpoint")
            or artist_payload.get("model")
            or "default_sd_checkpoint"
        )
        final_params: dict[str, Any] = {
            "checkpoint": checkpoint,
            "positive_prompt": bundle.prompt.positive,
            "negative_prompt": bundle.prompt.negative,
            "seed": seed if seed is not None else params.get("seed", 0),
            "width": width,
            "height": height,
            "steps": params.get("steps", artist_payload.get("steps", 28)),
            "cfg_scale": params.get(
                "cfg_scale",
                params.get("cfg", artist_payload.get("cfg_scale", 7.0)),
            ),
            "sampler": params.get("sampler", artist_payload.get("sampler", "Euler a")),
            "scheduler": params.get("scheduler", artist_payload.get("scheduler", "automatic")),
            "vae": params.get("vae", artist_payload.get("vae")),
            "clip_skip": params.get("clip_skip", artist_payload.get("clip_skip", 1)),
            "loras": params.get("loras", artist_payload.get("loras", [])),
            "embeddings": params.get("embeddings", artist_payload.get("embeddings", [])),
            "controlnet": params.get("controlnet", artist_payload.get("controlnet", [])),
            "hires_fix": params.get("hires_fix", artist_payload.get("hires_fix", {})),
        }
        final_params.update(
            preserve_extra_params(params, reserved=set(final_params) | {"model", "cfg"})
        )
        return final_params
