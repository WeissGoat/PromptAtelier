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

LEGACY_NAI4_QUALITY_PROMPT = ",::,very aesthetic, masterpiece, no text"
LEGACY_DEFAULT_NEGATIVE_PROMPT = (
    "lowres, {bad}, error, fewer, extra, missing, worst quality, jpeg artifacts, "
    "bad quality, watermark, unfinished, displeasing, chromatic aberration, signature, "
    "extra digits, artistic error, username, scan, [abstract], lowres, {bad}, error, "
    "fewer, extra, missing, worst quality, jpeg artifacts, bad quality, watermark, "
    "unfinished, displeasing, chromatic aberration, signature, extra digits, "
    "artistic error, username, scan, [abstract], bad anatomy, body writing, bad hands, "
    "worst quality, low quality, normal quality, mutation, mutated, extra limb, "
    "poorly drawn hands, missing limb, floating limbs, disconnected limbs, malformed hands, "
    "long neck, long body, extra fingers, mosaic, bad faces, bad face, bad eyes, "
    "bad feet, extra toes,censored"
)


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


def _join_legacy_prompt_parts(*parts: str | list[str] | None) -> str:
    items: list[str] = []
    for part in parts:
        if not part:
            continue
        if isinstance(part, list):
            items.extend(_legacy_prompt_tags(",".join(str(item) for item in part)))
            continue
        text = str(part).strip()
        if text in {"", ","}:
            continue
        items.extend(_legacy_prompt_tags(text.strip(",").strip()))
    return f"{','.join(items)}," if items else ""


def _legacy_prompt_tags(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


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
                "character_ref": bundle.meta.character_ref,
                "action_ref": bundle.meta.action_ref,
                "background_ref": bundle.meta.background_ref,
                "style_ref": bundle.meta.style_ref,
                "composer_type": bundle.meta.composer_type,
                "composer_version": bundle.meta.composer_version,
                "character_scope": bundle.meta.composition.character_scope,
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
        prompt_mode = str(params.get("prompt_mode", "compose"))
        legacy_style = isinstance(style, NovelAIStyle) or bool(style_payload.get("legacy_compat"))
        if prompt_mode == "legacy-final":
            # 旧 run_action 对比时，PNG 里已经有最终 prompt；这里不能再叠加画风和质量词。
            positive = bundle.prompt.positive.strip()
            negative = (
                bundle.prompt.negative.strip()
                if bundle.prompt.negative
                else self._legacy_negative_prompt(
                    bundle=bundle,
                    style_prompt=style_prompt,
                )
            )
        elif legacy_style:
            positive = self._legacy_positive_prompt(
                bundle=bundle,
                style_payload=style_payload,
                style_prompt=style_prompt,
            )
            negative = self._legacy_negative_prompt(
                bundle=bundle,
                style_prompt=style_prompt,
            )
        else:
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

        if legacy_style:
            positive = self._legacy_runtime_clean_positive(
                positive,
                style_payload=style_payload,
            )
            negative = self._legacy_runtime_clean_negative(negative)

        sampler = params.get("sampler", "k_dpmpp_2s_ancestral" if legacy_style else "k_euler")
        scheduler = params.get("noise_schedule", params.get("scheduler", "native"))
        if sampler == "ddim":
            sampler = "ddim_v3"

        # 这些默认值参考 ComfyUI_NAIDGenerator 的 V4/V4.5 请求结构。
        final_params: dict[str, Any] = {
            "params_version": 1,
            "width": width,
            "height": height,
            "scale": params.get("scale", 6.0 if legacy_style else 5.0),
            "sampler": sampler,
            "steps": params.get("steps", 28),
            "seed": seed or params.get("seed") or 0,
            "n_samples": params.get("n_samples", 1),
            "ucPreset": 3,
            "qualityToggle": False,
            "sm": params.get("sm", True if legacy_style else False) and sampler != "ddim_v3",
            "sm_dyn": params.get("sm_dyn", False) and sampler != "ddim_v3",
            "dynamic_thresholding": params.get("dynamic_thresholding", False),
            "controlnet_strength": params.get("controlnet_strength", 1.0),
            "legacy": params.get("legacy", False),
            "add_original_image": params.get("add_original_image", True if legacy_style else False),
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
            "director_reference_images": params.get("director_reference_images", []),
            "extra_noise_seed": params.get("extra_noise_seed", seed or params.get("seed") or 0),
            "v4_prompt": {
                "use_coords": False,
                "use_order": params.get("use_order", True if legacy_style else False),
                "caption": {"base_caption": positive, "char_captions": []},
            },
            "v4_negative_prompt": {
                "use_coords": False,
                "use_order": False,
                "caption": {"base_caption": negative, "char_captions": []},
            },
        }
        final_params.update(self._preserve_supported_extras(params))
        for key in ("prefer_brownian", "deliberate_euler_ancestral_bug"):
            if key in params:
                final_params[key] = params[key]

        if sampler == "k_euler_ancestral" and scheduler != "native":
            final_params["deliberate_euler_ancestral_bug"] = False
            final_params["prefer_brownian"] = True

        return final_params

    def _legacy_positive_prompt(
        self,
        *,
        bundle: PromptBundle,
        style_payload: dict[str, Any],
        style_prompt: dict[str, list[str]],
    ) -> str:
        flags = set(style_payload.get("flags") or [])
        quality_prompt = (
            ""
            if flags.intersection({"not_quailty_prompts", "not_quality_prompts"})
            else LEGACY_NAI4_QUALITY_PROMPT
        )
        parts: list[str | list[str] | None] = []
        if style_prompt["prompt_prefix"]:
            parts.append(style_prompt["prompt_prefix"])
        parts.extend(
            [
                bundle.prompt.positive,
                style_prompt["prompt_suffix"],
                quality_prompt,
            ]
        )
        return _join_legacy_prompt_parts(*parts)

    def _legacy_negative_prompt(
        self,
        *,
        bundle: PromptBundle,
        style_prompt: dict[str, list[str]],
    ) -> str:
        if not style_prompt["negative_prompt"]:
            extra = _join_legacy_prompt_parts(
                style_prompt["after_negative_prompt"],
                bundle.prompt.negative,
            ).strip(",")
            if extra:
                return f"{LEGACY_DEFAULT_NEGATIVE_PROMPT},{extra},"
            return f"{LEGACY_DEFAULT_NEGATIVE_PROMPT},"
        base_negative = style_prompt["negative_prompt"]
        return _join_legacy_prompt_parts(
            base_negative,
            style_prompt["after_negative_prompt"],
            bundle.prompt.negative,
        )

    def _legacy_runtime_clean_positive(
        self,
        text: str,
        *,
        style_payload: dict[str, Any],
    ) -> str:
        # 旧 tags_machine 在 NAi.generate_image 发请求前还会清理 prompt；
        # 这里仅在 legacy 兼容路径复刻，避免污染新架构默认行为。
        text = text.replace("\xa0", " ").replace("@ @", "@_@")
        if self._legacy_should_clean_movie_style_artists(style_payload):
            text = self._legacy_clean_movie_style_artists(text)
        text = self._legacy_loop_replace(text, "bruises", "scratches")
        for _ in range(5):
            text = self._legacy_loop_replace(text, ",,", ",")
            text = self._legacy_loop_replace(text, "  ", " ")
            text = self._legacy_loop_replace(text, ",}", "}")
            text = self._legacy_loop_replace(text, "{,", "{")
            text = self._legacy_loop_replace(text, "[,", "[")
            text = self._legacy_loop_replace(text, ",]", "]")
            text = self._legacy_loop_replace(text, "{}")
            text = self._legacy_loop_replace(text, "[]")
        text = self._legacy_loop_replace(text, "toe ring", "toes")
        text = self._legacy_loop_replace(text, "puffy nipples", "nipples")
        return self._legacy_loop_replace(text, "randoseru")

    def _legacy_should_clean_movie_style_artists(self, style_payload: dict[str, Any]) -> bool:
        style_ref = str(style_payload.get("style_ref") or "")
        style_path = str(style_payload.get("path") or "")
        marker = "\u52a8\u753b_\u7535\u5f71\u611f"
        return marker in style_ref or marker in style_path

    def _legacy_clean_movie_style_artists(self, text: str) -> str:
        clear_tokens = [
            "Jonpei",
            "huwari_(dnwls3010)",
            "piromizu",
            "yuzutei",
            "asahina_hikage",
            "atahuta",
            "elleciel.eud",
            "thanabis",
            "fumihiko (fu_mihi_ko)",
            "shisantian",
            "artist:mignon",
            "jp06",
            "Ixy",
            "shiro9jira",
            "barbarian_tk",
            "rokita",
            "hyocorou",
            "artist:deadflow",
            "onono_imoko",
            "yukiu_con",
            "maturiuta sorata",
            "asou(asabu202)",
            "ame (uten cancel)",
            "asou_(asabu202)",
            "nakkar",
            "rryiup",
            "cha_goma",
            "hiro (dismaless)",
            "armpit stubble",
        ]
        clear_words = (
            "oshinoko,isshi_pyuma,dsmile,raika9,papi (papiron100),"
            "mattaku mousuke,dikko,tianliang_duohe_fangdongye,curss,"
            "mamerakkkkko,misaka12003,lasto,fuya (tempupupu),yuran,"
            "akeyama kitsune,almic,artist:hiten,artist:ao+beni,"
            "artist:marumoru,hews,hiro_(dismaless),Kyokucho,hitomaru,"
            "onono_imoko,piromizu,torino_aqua,kanzaki_hiro,asahina_hikage,"
            "oniilus,superpig,kantoku,ipuu_(el-ane_koubou),fundoshi,"
            "xinzoruo,ishikei,artist:ningen_mame,artist:sho_(sho_lwlw),"
            "artist:mignon,artist:kedama milk,artist:ask_(askzy),"
            "artist:wanke,fujiyama,whoosaku,sameda_koban,konpeto,"
            "terasu_mc,hotate-chan,b-ginga,akai sashimi,akamoku,"
            "miyase mahiro,[shnva],simao (x x36131422),senro,kuzuvine,"
            "kuroduki (pieat),jima,hiten_(hitenkei),ask_(askzy),"
            "hanabi_(ocha),AS109,hitenkei,maccha (mochancc),gishu,"
            "kedama milk,akino komichi,morikura_en"
        )
        clear_tokens.extend(
            token.strip() for token in clear_words.split(",") if token.strip()
        )
        for token in clear_tokens:
            text = text.replace(token, ",")
            text = text.replace(token.lower(), ",")
        text = text.replace("oiled", "oiled skin")
        text = text.replace("oil,", "oiled skin")
        text = text.replace("fat,", ",")
        text = text.replace("ugly,", ",")
        text = text.replace("old,", ",")
        text = text.replace("skin skin", "skin")
        text = text.replace("oiled skin", ",")
        text = self._legacy_loop_replace(text, "{{{{", "{", "{{")
        return self._legacy_loop_replace(text, "}}}}", "}", "}}")

    def _legacy_runtime_clean_negative(self, text: str) -> str:
        # 旧入口对 UC 至少会清掉空权重括号；这会影响 NovelAI 实际出图。
        text = text.replace("\xa0", " ")
        for _ in range(5):
            text = text.replace("  ", " ")
            text = text.replace("{}", "")
            text = text.replace("[]", "")
        return text

    def _legacy_loop_replace(
        self,
        text: str,
        needle: str,
        replacement: str = "",
        replace_content: str | None = None,
    ) -> str:
        source = replace_content or needle
        while needle in text:
            updated = text.replace(source, replacement)
            if updated == text:
                break
            text = updated
        return text

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
            "director_reference_images",
            "extra_noise_seed",
            "v4_prompt",
            "v4_negative_prompt",
            "deliberate_euler_ancestral_bug",
            "prefer_brownian",
            "prompt_mode",
        }
        return {key: value for key, value in params.items() if key not in reserved}
