from __future__ import annotations

import copy
from typing import Any

from tags_machine_core.contracts import PromptBundle, RenderRequest, RenderSize
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.renderers.common import (
    preserve_extra_params,
    render_meta,
    renderer_style_payload,
)


class ComfyUIRenderAdapter:
    """把 PromptBundle 转成 ComfyUI dry-run 执行计划，不负责联网。"""

    backend = "comfyui"

    def build_request(
        self,
        bundle: PromptBundle,
        seed: int | None = None,
        width: int = 1024,
        height: int = 1024,
        model: str | None = None,
        action: str = "render-plan",
        params: dict[str, Any] | None = None,
        style: NodeDocument | dict[str, Any] | None = None,
    ) -> RenderRequest:
        style_payload = renderer_style_payload(style, self.backend)
        style_params = copy.deepcopy(style_payload.get("params", {}) or {})
        final_params = self._build_parameters(
            bundle=bundle,
            seed=seed,
            width=width,
            height=height,
            model=model,
            style_payload=style_payload,
            params={**style_params, **(params or {})},
        )
        return RenderRequest(
            backend=self.backend,
            prompt=bundle.prompt.positive,
            negative_prompt=bundle.prompt.negative,
            model=final_params.get("checkpoint"),
            seed=final_params["seed"],
            size=RenderSize(width=width, height=height),
            params=final_params,
            style_payload=style_payload,
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
        style_payload: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        checkpoint = (
            model
            or params.get("checkpoint")
            or params.get("model")
            or style_payload.get("checkpoint")
            or style_payload.get("model")
            or "default_comfy_checkpoint"
        )
        workflow = (
            params.get("workflow")
            or params.get("workflow_template")
            or style_payload.get("workflow")
            or style_payload.get("workflow_template")
            or "default"
        )
        final_params: dict[str, Any] = {
            "workflow": workflow,
            "checkpoint": checkpoint,
            "positive_prompt": bundle.prompt.positive,
            "negative_prompt": bundle.prompt.negative,
            "seed": seed if seed is not None else params.get("seed", 0),
            "width": width,
            "height": height,
            "steps": params.get("steps", style_payload.get("steps", 28)),
            "cfg": params.get("cfg", params.get("cfg_scale", style_payload.get("cfg", 7.0))),
            "sampler": params.get("sampler", style_payload.get("sampler", "euler")),
            "scheduler": params.get("scheduler", style_payload.get("scheduler", "normal")),
            "loras": params.get("loras", style_payload.get("loras", [])),
            "embeddings": params.get("embeddings", style_payload.get("embeddings", [])),
            "control": params.get("control", style_payload.get("control", {})),
            "node_overrides": params.get(
                "node_overrides",
                style_payload.get("node_overrides", {}),
            ),
        }
        final_params.update(
            preserve_extra_params(params, reserved=set(final_params) | {"model", "cfg_scale"})
        )
        return final_params
