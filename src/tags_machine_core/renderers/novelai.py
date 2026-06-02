from __future__ import annotations

import copy
import math
import random
import re
from typing import Any

from tags_machine_core.contracts import PromptBundle, RenderRequest, RenderSize
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.novelai_artist import NovelAIArtist
from tags_machine_core.nodes.resolved import ResolvedNodeSet
from tags_machine_core.renderers.common import (
    renderer_artist_payload,
    renderer_artist_prompt_parts,
)


NovelAIArtistInput = NovelAIArtist | NodeDocument | dict[str, Any] | None

_SEED_RANDOM = random.SystemRandom()
_NOVELAI_SEED_MIN = 0
_NOVELAI_SEED_MAX = 4294967295

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
DEFAULT_CHARACTER_CENTERS = [{"x": 0.5, "y": 0.5}]
MALE_CHARACTER_CAPTION = "boy, "


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


def _rejoin_prompt_tags(tags: list[str], *, legacy_artist: bool) -> str:
    if legacy_artist:
        return _join_legacy_prompt_parts(tags)
    return _join_prompt_parts(tags)


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
        artist: NovelAIArtistInput = None,
        resolved_nodes: ResolvedNodeSet | None = None,
    ) -> RenderRequest:
        artist = self._resolve_artist(artist, resolved_nodes)
        artist_payload = self._artist_payload(artist)
        artist_params = self._artist_params(artist, artist_payload)
        render_params = {**artist_params, **(params or {})}
        model = self._resolve_model(
            default_model=model,
            artist_payload=artist_payload,
            artist_params=artist_params,
            params=render_params,
        )
        render_params.pop("model", None)
        final_params = self._build_parameters(
            bundle=bundle,
            artist=artist,
            artist_payload=artist_payload,
            seed=seed,
            width=width,
            height=height,
            params=render_params,
            model=model,
            resolved_nodes=resolved_nodes,
        )
        prompt = final_params["prompt"]
        negative_prompt = final_params["negative_prompt"]
        character_prompt_meta = final_params.pop("_character_prompt_meta", None)
        if isinstance(character_prompt_meta, dict) and not character_prompt_meta:
            character_prompt_meta = None

        meta = {
            "action": action,
            "composer_type": bundle.meta.composer_type,
            "composer_version": bundle.meta.composer_version,
            "character_scope": bundle.meta.composition.character_scope,
            "prompt_cache_key": bundle.cache.cache_key,
        }
        trace_meta = self._node_trace_meta(bundle, resolved_nodes)
        if trace_meta:
            meta.update(trace_meta)
        if character_prompt_meta:
            meta["character_prompts"] = character_prompt_meta

        return RenderRequest(
            backend=self.backend,
            prompt=prompt,
            negative_prompt=negative_prompt,
            model=model,
            seed=seed,
            size=RenderSize(width=width, height=height),
            params=final_params,
            artist_payload=artist_payload,
            meta=meta,
        )

    def _build_parameters(
        self,
        bundle: PromptBundle,
        artist: NovelAIArtistInput,
        artist_payload: dict[str, Any],
        seed: int | None,
        width: int,
        height: int,
        params: dict[str, Any],
        model: str | None = None,
        resolved_nodes: ResolvedNodeSet | None = None,
    ) -> dict[str, Any]:
        artist_prompt = self._artist_prompt_parts(artist, artist_payload)
        prompt_mode = str(params.get("prompt_mode", "compose"))
        legacy_artist = isinstance(artist, NovelAIArtist) or bool(artist_payload.get("legacy_compat"))
        if prompt_mode == "legacy-final":
            # 旧 run_action 对比时，PNG 里已经有最终 prompt；这里不能再叠加画风和质量词。
            positive = bundle.prompt.positive.strip()
            negative = (
                bundle.prompt.negative.strip()
                if bundle.prompt.negative
                else self._legacy_negative_prompt(
                    bundle=bundle,
                    artist_prompt=artist_prompt,
                )
            )
        elif legacy_artist:
            positive = self._legacy_positive_prompt(
                bundle=bundle,
                artist_payload=artist_payload,
                artist_prompt=artist_prompt,
            )
            negative = self._legacy_negative_prompt(
                bundle=bundle,
                artist_prompt=artist_prompt,
            )
        else:
            positive = _join_prompt_parts(
                artist_prompt["prompt_prefix"],
                bundle.prompt.positive,
                artist_prompt["prompt_suffix"],
            )
            negative = _join_prompt_parts(
                bundle.prompt.negative,
                artist_prompt["negative_prompt"],
                artist_prompt["after_negative_prompt"],
            )

        if legacy_artist:
            positive = self._legacy_runtime_clean_positive(
                positive,
                artist_payload=artist_payload,
            )
            negative = self._legacy_runtime_clean_negative(negative)

        (
            positive,
            negative,
            char_captions,
            negative_char_captions,
            character_prompt_meta,
        ) = self._apply_character_prompts(
            bundle=bundle,
            positive=positive,
            negative=negative,
            model=model,
            params=params,
            resolved_nodes=resolved_nodes,
            legacy_artist=legacy_artist,
        )

        width = _validate_int_parameter("width", width, minimum=64, maximum=49152)
        height = _validate_int_parameter("height", height, minimum=64, maximum=49152)
        sampler = params.get("sampler", "k_dpmpp_2s_ancestral" if legacy_artist else "k_euler")
        scheduler = params.get("noise_schedule", params.get("scheduler", "native"))
        if sampler == "ddim":
            sampler = "ddim_v3"
        resolved_seed = _resolve_seed(seed, params.get("seed"))
        extra_noise_seed = _resolve_extra_noise_seed(params.get("extra_noise_seed"), resolved_seed)
        scale = _validate_number_parameter(
            "scale",
            params.get("scale", 6.0 if legacy_artist else 5.0),
            minimum=0,
            maximum=10,
        )
        steps = _validate_int_parameter("steps", params.get("steps", 28), minimum=1, maximum=50)
        n_samples = _validate_int_parameter(
            "n_samples",
            params.get("n_samples", 1),
            minimum=1,
            maximum=_max_n_samples(width, height),
        )
        cfg_rescale = _validate_number_parameter(
            "cfg_rescale",
            params.get("cfg_rescale", 0.0),
            minimum=0,
            maximum=1,
        )
        uncond_scale = _validate_number_parameter(
            "uncond_scale",
            params.get("uncond_scale", 0.0),
            minimum=0,
            maximum=1.5,
        )
        controlnet_strength = _validate_number_parameter(
            "controlnet_strength",
            params.get("controlnet_strength", 1.0),
            minimum=0.1,
            maximum=2,
        )

        # 这些默认值参考 ComfyUI_NAIDGenerator 的 V4/V4.5 请求结构。
        final_params: dict[str, Any] = {
            "params_version": 1,
            "width": width,
            "height": height,
            "scale": scale,
            "sampler": sampler,
            "steps": steps,
            "seed": resolved_seed,
            "n_samples": n_samples,
            "ucPreset": 3,
            "qualityToggle": False,
            "sm": params.get("sm", True if legacy_artist else False) and sampler != "ddim_v3",
            "sm_dyn": params.get("sm_dyn", False) and sampler != "ddim_v3",
            "dynamic_thresholding": params.get("dynamic_thresholding", False),
            "controlnet_strength": controlnet_strength,
            "legacy": params.get("legacy", False),
            "add_original_image": params.get("add_original_image", True if legacy_artist else False),
            "cfg_rescale": cfg_rescale,
            "noise_schedule": scheduler,
            "legacy_v3_extend": params.get("legacy_v3_extend", False),
            "uncond_scale": uncond_scale,
            "negative_prompt": negative,
            "prompt": positive,
            "reference_image_multiple": params.get("reference_image_multiple", []),
            "reference_information_extracted_multiple": params.get(
                "reference_information_extracted_multiple", []
            ),
            "reference_strength_multiple": params.get("reference_strength_multiple", []),
            "director_reference_images": params.get("director_reference_images", []),
            "extra_noise_seed": extra_noise_seed,
            "v4_prompt": {
                "use_coords": False,
                "use_order": params.get("use_order", True if legacy_artist else False),
                "caption": {"base_caption": positive, "char_captions": char_captions},
            },
            "v4_negative_prompt": {
                "use_coords": False,
                "use_order": False,
                "caption": {
                    "base_caption": negative,
                    "char_captions": negative_char_captions,
                },
            },
        }
        if char_captions:
            final_params["characterPrompts"] = _character_prompts_parameter(
                char_captions,
                negative_char_captions,
            )
        if character_prompt_meta is not None:
            final_params["_character_prompt_meta"] = character_prompt_meta
        final_params.update(self._preserve_supported_extras(params))
        for key in ("prefer_brownian", "deliberate_euler_ancestral_bug"):
            if key in params:
                final_params[key] = params[key]

        if sampler == "k_euler_ancestral" and scheduler != "native":
            final_params["deliberate_euler_ancestral_bug"] = False
            final_params["prefer_brownian"] = True

        return final_params

    def _apply_character_prompts(
        self,
        *,
        bundle: PromptBundle,
        positive: str,
        negative: str,
        model: str | None,
        params: dict[str, Any],
        resolved_nodes: ResolvedNodeSet | None,
        legacy_artist: bool,
    ) -> tuple[
        str,
        str,
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, Any] | None,
    ]:
        config = params.get("character_prompts")
        if not isinstance(config, dict) or config.get("mode") != "auto":
            return positive, negative, [], [], None
        if not self._supports_character_prompts(model):
            return (
                positive,
                negative,
                [],
                [],
                {"mode": "auto", "status": "unsupported_model"},
            )
        materials = self._character_prompt_materials(bundle, resolved_nodes)
        if not materials:
            return (
                positive,
                negative,
                [],
                [],
                {"mode": "auto", "status": "no_characters"},
            )

        base_tags = _legacy_prompt_tags(positive)
        negative_tags = _legacy_prompt_tags(negative)
        char_captions: list[dict[str, Any]] = []
        negative_char_captions: list[dict[str, Any]] = []
        removed_positive_tags: list[str] = []
        removed_negative_tags: list[str] = []
        matched_positive_tag_set: set[str] = set()
        matched_negative_tag_set: set[str] = set()
        default_caption_prefix = str(config.get("default_caption_prefix", "girl")).strip()
        max_characters = _bounded_int(config.get("max_characters"), default=6, minimum=1, maximum=6)
        male_caption_added = False

        for material in materials[:max_characters]:
            candidate_positive_tags = [
                str(item).strip()
                for item in material.get("positive_tags", [])
                if str(item).strip()
            ]
            candidate_negative_tags = [
                str(item).strip()
                for item in material.get("negative_tags", [])
                if str(item).strip()
            ]
            matched_positive_tags: list[str] = []
            matched_negative_tags: list[str] = []
            for tag in candidate_positive_tags:
                if tag in base_tags:
                    matched_positive_tags.append(tag)
                    removed_positive_tags.append(tag)
                    matched_positive_tag_set.add(tag)
            for tag in candidate_negative_tags:
                if tag in negative_tags:
                    matched_negative_tags.append(tag)
                    removed_negative_tags.append(tag)
                    matched_negative_tag_set.add(tag)

            if matched_positive_tags:
                caption_parts = (
                    [default_caption_prefix, *matched_positive_tags]
                    if default_caption_prefix
                    else matched_positive_tags
                )
                char_captions.append(
                    {
                        "char_caption": _join_prompt_parts(caption_parts),
                        "centers": copy.deepcopy(DEFAULT_CHARACTER_CENTERS),
                    }
                )
                negative_char_captions.append(
                    {
                        "char_caption": (
                            _join_prompt_parts(matched_negative_tags)
                            if matched_negative_tags
                            else ""
                        ),
                        "centers": copy.deepcopy(DEFAULT_CHARACTER_CENTERS),
                    }
                )

        if (
            char_captions
            and _enabled_config(config.get("add_male_caption"), default=True)
            and _contains_male_character(base_tags)
            and not _contains_male_character(
                [caption.get("char_caption") for caption in char_captions]
            )
        ):
            char_captions.append(
                {
                    "char_caption": MALE_CHARACTER_CAPTION,
                    "centers": copy.deepcopy(DEFAULT_CHARACTER_CENTERS),
                }
            )
            male_caption_added = True

        negative_char_captions = _pad_negative_character_captions(
            negative_char_captions,
            target_count=len(char_captions),
        )
        base_tags = [tag for tag in base_tags if tag not in matched_positive_tag_set]
        negative_tags = [tag for tag in negative_tags if tag not in matched_negative_tag_set]

        return (
            _rejoin_prompt_tags(base_tags, legacy_artist=legacy_artist),
            _rejoin_prompt_tags(negative_tags, legacy_artist=legacy_artist),
            char_captions,
            negative_char_captions,
            {
                "mode": "auto",
                "count": len(char_captions),
                "removed_positive_tags": removed_positive_tags,
                "removed_negative_tags": removed_negative_tags,
                "male_caption_added": male_caption_added,
            },
        )

    def _supports_character_prompts(self, model: str | None) -> bool:
        return str(model or "").startswith("nai-diffusion-4")

    def _character_prompt_materials(
        self,
        bundle: PromptBundle,
        resolved_nodes: ResolvedNodeSet | None,
    ) -> list[dict[str, Any]]:
        if resolved_nodes:
            return [
                _raw_character_material(
                    node=item.node,
                    ref=item.ref,
                    index=item.index,
                )
                for item in resolved_nodes.characters()
            ]
        materials = bundle.meta.extra.get("character_materials")
        if isinstance(materials, list) and materials:
            return [item for item in materials if isinstance(item, dict)]
        return []

    def _node_trace_meta(
        self,
        bundle: PromptBundle,
        resolved_nodes: ResolvedNodeSet | None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if bundle.meta.nodes:
            result["node_refs"] = [
                node.model_dump(mode="json", exclude_none=True)
                for node in bundle.meta.nodes
            ]
            result["source_nodes"] = [node.ref for node in bundle.meta.nodes]
        elif resolved_nodes:
            prompt_nodes = list(resolved_nodes)
            if prompt_nodes:
                result["node_refs"] = [item.as_ref() for item in prompt_nodes]
                result["source_nodes"] = [item.node.source_ref() for item in prompt_nodes]

        character_materials = bundle.meta.extra.get("character_materials")
        if isinstance(character_materials, list) and character_materials:
            result["character_materials"] = character_materials
        elif resolved_nodes:
            materials = self._character_prompt_materials(bundle, resolved_nodes)
            if materials:
                result["character_materials"] = materials
        return result

    def _legacy_positive_prompt(
        self,
        *,
        bundle: PromptBundle,
        artist_payload: dict[str, Any],
        artist_prompt: dict[str, list[str]],
    ) -> str:
        flags = set(artist_payload.get("flags") or [])
        quality_prompt = (
            ""
            if flags.intersection({"not_quailty_prompts", "not_quality_prompts"})
            else LEGACY_NAI4_QUALITY_PROMPT
        )
        parts: list[str | list[str] | None] = []
        if artist_prompt["prompt_prefix"]:
            parts.append(artist_prompt["prompt_prefix"])
        parts.extend(
            [
                bundle.prompt.positive,
                artist_prompt["prompt_suffix"],
                quality_prompt,
            ]
        )
        return _join_legacy_prompt_parts(*parts)

    def _legacy_negative_prompt(
        self,
        *,
        bundle: PromptBundle,
        artist_prompt: dict[str, list[str]],
    ) -> str:
        if not artist_prompt["negative_prompt"]:
            extra = _join_legacy_prompt_parts(
                artist_prompt["after_negative_prompt"],
                bundle.prompt.negative,
            ).strip(",")
            if extra:
                return f"{LEGACY_DEFAULT_NEGATIVE_PROMPT},{extra},"
            return f"{LEGACY_DEFAULT_NEGATIVE_PROMPT},"
        base_negative = artist_prompt["negative_prompt"]
        return _join_legacy_prompt_parts(
            base_negative,
            artist_prompt["after_negative_prompt"],
            bundle.prompt.negative,
        )

    def _legacy_runtime_clean_positive(
        self,
        text: str,
        *,
        artist_payload: dict[str, Any],
    ) -> str:
        # 旧 tags_machine 在 NAi.generate_image 发请求前还会清理 prompt；
        # 这里仅在 legacy 兼容路径复刻，避免污染新架构默认行为。
        text = text.replace("\xa0", " ").replace("@ @", "@_@")
        if self._legacy_should_clean_movie_style_artists(artist_payload):
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

    def _legacy_should_clean_movie_style_artists(self, artist_payload: dict[str, Any]) -> bool:
        artist_ref = str(artist_payload.get("artist_ref") or "")
        artist_path = str(artist_payload.get("path") or "")
        marker = "\u52a8\u753b_\u7535\u5f71\u611f"
        return marker in artist_ref or marker in artist_path

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
        text = self._legacy_remove_prompt_tags(text, clear_tokens)
        text = text.replace("oiled", "oiled skin")
        text = text.replace("oil,", "oiled skin")
        text = text.replace("fat,", ",")
        text = text.replace("ugly,", ",")
        text = text.replace("old,", ",")
        text = text.replace("skin skin", "skin")
        text = text.replace("oiled skin", ",")
        text = self._legacy_loop_replace(text, "{{{{", "{", "{{")
        return self._legacy_loop_replace(text, "}}}}", "}", "}}")

    def _legacy_remove_prompt_tags(self, text: str, clear_tokens: list[str]) -> str:
        normalized_clear_tokens = {
            self._legacy_normalize_prompt_tag(token)
            for token in clear_tokens
            if self._legacy_normalize_prompt_tag(token)
        }
        kept_tags: list[str] = []
        for tag in text.split(","):
            if not tag.strip():
                kept_tags.append(tag)
                continue
            normalized_tag = self._legacy_normalize_prompt_tag(tag)
            if any(token in normalized_tag for token in normalized_clear_tokens):
                continue
            kept_tags.append(tag)
        return ",".join(kept_tags)

    def _legacy_normalize_prompt_tag(self, tag: str) -> str:
        text = tag.strip().lower()
        text = text.replace("artist:", "")
        text = text.replace("artist：", "")
        text = text.replace("_", " ")
        text = re.sub(r"[\[\]{}()]+", "", text)
        return re.sub(r"\s+", " ", text).strip()

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

    def _resolve_artist(
        self,
        artist: NovelAIArtistInput,
        resolved_nodes: ResolvedNodeSet | None,
    ) -> NovelAIArtistInput:
        if artist is not None:
            return artist
        if not resolved_nodes:
            return None
        first_artist = resolved_nodes.first("artist")
        return first_artist.node if first_artist else None

    def _artist_payload(self, artist: NovelAIArtistInput) -> dict[str, Any]:
        if artist is None:
            return {}
        if isinstance(artist, NovelAIArtist):
            return artist.artist_payload()
        return renderer_artist_payload(artist, self.backend)

    def _artist_params(
        self,
        artist: NovelAIArtistInput,
        artist_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(artist, NovelAIArtist):
            return copy.deepcopy(artist.params)
        return copy.deepcopy(artist_payload.get("params", {}) or {})

    def _resolve_model(
        self,
        *,
        default_model: str | None,
        artist_payload: dict[str, Any],
        artist_params: dict[str, Any],
        params: dict[str, Any],
    ) -> str | None:
        explicit_model = (
            _optional_text(params.get("model"))
            or _optional_text(artist_payload.get("model"))
            or _optional_text(artist_params.get("model"))
        )
        if explicit_model:
            return explicit_model
        if params.get("_legacy_run_prompt_compat"):
            return "nai-diffusion-3"
        if self._is_legacy_nai3_artist(
            artist_payload=artist_payload,
            artist_params=artist_params,
        ):
            return "nai-diffusion-3"
        return default_model

    def _is_legacy_nai3_artist(
        self,
        *,
        artist_payload: dict[str, Any],
        artist_params: dict[str, Any],
    ) -> bool:
        # 旧 tags.txt 没有 gen_json 时通常是 NAI3 画风，不能强行套 NAI4.5 请求。
        if not artist_payload.get("legacy_compat"):
            return False
        return not artist_params

    def _artist_prompt_parts(
        self,
        artist: NovelAIArtistInput,
        artist_payload: dict[str, Any],
    ) -> dict[str, list[str]]:
        if artist is None:
            return {
                "prompt_prefix": [],
                "prompt_suffix": [],
                "negative_prompt": [],
                "after_negative_prompt": [],
            }
        if isinstance(artist, NovelAIArtist):
            return {
                "prompt_prefix": artist.prompt_prefix,
                "prompt_suffix": artist.prompt_suffix,
                "negative_prompt": [artist.negative_prompt] if artist.negative_prompt else [],
                "after_negative_prompt": (
                    [artist.after_negative_prompt] if artist.after_negative_prompt else []
                ),
            }
        return renderer_artist_prompt_parts(artist, self.backend)

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
            "characterPrompts",
            "deliberate_euler_ancestral_bug",
            "prefer_brownian",
            "prompt_mode",
            "character_prompts",
            "_legacy_run_prompt_compat",
        }
        return {key: value for key, value in params.items() if key not in reserved}


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _enabled_config(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _contains_male_character(values: list[Any] | tuple[Any, ...]) -> bool:
    return any(_is_male_character_tag(str(value)) for value in values if value is not None)


def _is_male_character_tag(value: str) -> bool:
    text = _normalize_character_prompt_tag(value)
    if not text:
        return False
    if re.fullmatch(r"\d+\s*boys?", text):
        return True
    if re.search(r"\b(boy|boys|male|males|man|men)\b", text):
        return True
    return False


def _normalize_character_prompt_tag(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"^[\[\]{}()]+|[\[\]{}()]+$", "", text)
    text = text.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip(" ,")


def _pad_negative_character_captions(
    captions: list[dict[str, Any]],
    *,
    target_count: int,
) -> list[dict[str, Any]]:
    result = list(captions)
    while len(result) < target_count:
        result.append(
            {
                "char_caption": "",
                "centers": copy.deepcopy(DEFAULT_CHARACTER_CENTERS),
            }
        )
    return result


def _character_prompts_parameter(
    char_captions: list[dict[str, Any]],
    negative_char_captions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, caption in enumerate(char_captions):
        negative_caption = (
            negative_char_captions[index] if index < len(negative_char_captions) else {}
        )
        centers = caption.get("centers")
        center = centers[0] if isinstance(centers, list) and centers else {"x": 0.5, "y": 0.5}
        items.append(
            {
                "prompt": str(caption.get("char_caption") or ""),
                "uc": str(negative_caption.get("char_caption") or ""),
                "center": copy.deepcopy(center),
                "enabled": True,
            }
        )
    return items


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _resolve_seed(explicit_seed: int | None, params_seed: Any) -> int:
    resolved_explicit = (
        _validate_seed("seed", explicit_seed) if explicit_seed is not None else None
    )
    resolved_params = _validate_seed("seed", params_seed) if params_seed is not None else None
    if resolved_explicit is not None:
        return resolved_explicit
    if resolved_params is not None:
        return resolved_params
    return _SEED_RANDOM.randint(_NOVELAI_SEED_MIN, _NOVELAI_SEED_MAX)


def _resolve_extra_noise_seed(value: Any, resolved_seed: int) -> int:
    if value is None:
        return resolved_seed
    return _validate_seed("extra_noise_seed", value)


def _validate_seed(name: str, value: Any) -> int:
    return _validate_int_parameter(
        name,
        value,
        minimum=_NOVELAI_SEED_MIN,
        maximum=_NOVELAI_SEED_MAX,
    )


def _validate_int_parameter(
    name: str,
    value: Any,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool):
        raise ValueError(_range_error(name, value, minimum, maximum))
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(_range_error(name, value, minimum, maximum))
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(_range_error(name, value, minimum, maximum)) from None
    if parsed < minimum or parsed > maximum:
        raise ValueError(_range_error(name, value, minimum, maximum))
    return parsed


def _validate_number_parameter(
    name: str,
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise ValueError(_range_error(name, value, minimum, maximum))
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(_range_error(name, value, minimum, maximum)) from None
    if not math.isfinite(parsed):
        raise ValueError(_range_error(name, value, minimum, maximum))
    if parsed < minimum or parsed > maximum:
        raise ValueError(_range_error(name, value, minimum, maximum))
    return parsed


def _range_error(name: str, value: Any, minimum: int | float, maximum: int | float) -> str:
    return f"NovelAI parameter {name} must be between {minimum} and {maximum}, got {value!r}"


def _max_n_samples(width: int, height: int) -> int:
    pixels = width * height
    if pixels <= 512 * 704:
        return 8
    if pixels <= 640 * 640:
        return 6
    if pixels <= 1024 * 3072:
        return 4
    return 0


def _raw_character_material(
    *,
    node: NodeDocument,
    ref: str,
    index: int,
) -> dict[str, Any]:
    return {
        "ref": ref,
        "id": node.id,
        "index": index,
        "used_sections": list(node.tags.keys()),
        "suppressed_sections": [],
        "positive_tags": node.all_tags(),
        "negative_tags": list(node.negative_prompt) + node.negative_texts(None),
    }
