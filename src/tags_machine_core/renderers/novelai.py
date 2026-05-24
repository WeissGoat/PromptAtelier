from __future__ import annotations

import copy
from typing import Any

from tags_machine_core.contracts import PromptBundle, RenderRequest, RenderSize
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.renderers.common import (
    renderer_style_payload,
    renderer_style_prompt_parts,
)
from tags_machine_core.renderers.novelai_style import NovelAIStyle


NovelAIStyleInput = NovelAIStyle | NodeDocument | dict[str, Any] | None


def _join_prompt_parts(*parts: str | list[str] | None) -> str:
    items: list[str] = []
    for part in parts:
        if not part:
            continue
        if isinstance(part, list):
            items.extend(str(item).strip(" ,") for item in part if str(item).strip(" ,"))
        else:
            text = str(part).strip(" ,")
            if text:
                items.append(text)
    return ", ".join(items)


class NovelAIRenderAdapter:
    """把 PromptBundle 转成现代 NovelAI 请求参数，但不负责联网。"""

    backend = "novelai"

    def build_request(
        self,
        bundle: PromptBundle,
        seed: int | None = None,
        width: int = 1024,
        height: int = 1024,
        model: str = "nai-diffusion-4-5-full",
        action: str = "generate",
        params: dict[str, Any] | None = None,
        style: NovelAIStyleInput = None,
    ) -> RenderRequest:
        style_payload = self._style_payload(style)
        style_params = self._style_params(style, style_payload)
        model = style_params.pop("model", style_payload.get("model", model))
        final_params = self._build_parameters(
            bundle=bundle,
            style=style,
            style_payload=style_payload,
            seed=seed,
            width=width,
            height=height,
            params={**style_params, **(params or {})},
        )
        prompt = final_params["prompt"]
        negative_prompt = final_params["negative_prompt"]

        return RenderRequest(
            backend=self.backend,
            prompt=prompt,
            negative_prompt=negative_prompt,
            model=model,
            seed=seed,
            size=RenderSize(width=width, height=height),
            params=final_params,
            style_payload=style_payload,
            meta={
                "action": action,
                "style_ref": bundle.meta.style_ref,
                "composer_type": bundle.meta.composer_type,
                "composer_version": bundle.meta.composer_version,
                "prompt_cache_key": bundle.cache.cache_key,
            },
        )

    def _build_parameters(
        self,
        bundle: PromptBundle,
        style: NovelAIStyleInput,
        style_payload: dict[str, Any],
        seed: int | None,
        width: int,
        height: int,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        style_prompt = self._style_prompt_parts(style, style_payload)
        positive = _join_prompt_parts(
            style_prompt["prompt_prefix"],
            bundle.prompt.positive,
            style_prompt["prompt_suffix"],
        )
        negative = _join_prompt_parts(
            bundle.prompt.negative,
            style_prompt["negative_prompt"],
            style_prompt["after_negative_prompt"],
        )

        sampler = params.get("sampler", "k_euler")
        scheduler = params.get("noise_schedule", params.get("scheduler", "native"))
        if sampler == "ddim":
            sampler = "ddim_v3"

        # 这些默认值参考 ComfyUI_NAIDGenerator 的 V4/V4.5 请求结构。
        final_params: dict[str, Any] = {
            "params_version": 1,
            "width": width,
            "height": height,
            "scale": params.get("scale", 5.0),
            "sampler": sampler,
            "steps": params.get("steps", 28),
            "seed": seed or params.get("seed") or 0,
            "n_samples": params.get("n_samples", 1),
            "ucPreset": 3,
            "qualityToggle": False,
            "sm": params.get("sm", False) and sampler != "ddim_v3",
            "sm_dyn": params.get("sm_dyn", False) and sampler != "ddim_v3",
            "dynamic_thresholding": params.get("dynamic_thresholding", False),
            "controlnet_strength": params.get("controlnet_strength", 1.0),
            "legacy": params.get("legacy", False),
            "add_original_image": params.get("add_original_image", False),
            "cfg_rescale": params.get("cfg_rescale", 0.0),
            "noise_schedule": scheduler,
            "legacy_v3_extend": params.get("legacy_v3_extend", False),
            "uncond_scale": params.get("uncond_scale", 0.0),
            "negative_prompt": negative,
            "prompt": positive,
            "reference_image_multiple": params.get("reference_image_multiple", []),
            "reference_information_extracted_multiple": params.get(
                "reference_information_extracted_multiple", []
            ),
            "reference_strength_multiple": params.get("reference_strength_multiple", []),
            "extra_noise_seed": params.get("extra_noise_seed", seed or params.get("seed") or 0),
            "v4_prompt": {
                "use_coords": False,
                "use_order": False,
                "caption": {"base_caption": positive, "char_captions": []},
            },
            "v4_negative_prompt": {
                "use_coords": False,
                "use_order": False,
                "caption": {"base_caption": negative, "char_captions": []},
            },
        }
        final_params.update(self._preserve_supported_extras(params))

        if sampler == "k_euler_ancestral" and scheduler != "native":
            final_params["deliberate_euler_ancestral_bug"] = False
            final_params["prefer_brownian"] = True

        return final_params

    def _style_payload(self, style: NovelAIStyleInput) -> dict[str, Any]:
        if style is None:
            return {}
        if isinstance(style, NovelAIStyle):
            return style.style_payload()
        return renderer_style_payload(style, self.backend)

    def _style_params(
        self,
        style: NovelAIStyleInput,
        style_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(style, NovelAIStyle):
            return copy.deepcopy(style.params)
        return copy.deepcopy(style_payload.get("params", {}) or {})

    def _style_prompt_parts(
        self,
        style: NovelAIStyleInput,
        style_payload: dict[str, Any],
    ) -> dict[str, list[str]]:
        if style is None:
            return {
                "prompt_prefix": [],
                "prompt_suffix": [],
                "negative_prompt": [],
                "after_negative_prompt": [],
            }
        if isinstance(style, NovelAIStyle):
            return {
                "prompt_prefix": style.prompt_prefix,
                "prompt_suffix": style.prompt_suffix,
                "negative_prompt": [style.negative_prompt] if style.negative_prompt else [],
                "after_negative_prompt": (
                    [style.after_negative_prompt] if style.after_negative_prompt else []
                ),
            }
        return renderer_style_prompt_parts(style, self.backend)

    def _preserve_supported_extras(self, params: dict[str, Any]) -> dict[str, Any]:
        # 这里只保留 adapter 没有显式标准化处理的扩展字段。
        reserved = {
            "params_version",
            "width",
            "height",
            "scale",
            "sampler",
            "steps",
            "seed",
            "n_samples",
            "ucPreset",
            "qualityToggle",
            "sm",
            "sm_dyn",
            "dynamic_thresholding",
            "controlnet_strength",
            "legacy",
            "add_original_image",
            "cfg_rescale",
            "noise_schedule",
            "legacy_v3_extend",
            "uncond_scale",
            "negative_prompt",
            "prompt",
            "reference_image_multiple",
            "reference_information_extracted_multiple",
            "reference_strength_multiple",
            "extra_noise_seed",
            "v4_prompt",
            "v4_negative_prompt",
            "deliberate_euler_ancestral_bug",
            "prefer_brownian",
        }
        return {key: value for key, value in params.items() if key not in reserved}
