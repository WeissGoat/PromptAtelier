from __future__ import annotations

import copy
from typing import Any

from tags_machine_core.contracts import PromptBundle
from tags_machine_core.nodes.models import NodeDocument


def renderer_style_payload(
    style_node: NodeDocument | dict[str, Any] | None,
    backend: str,
) -> dict[str, Any]:
    if style_node is None:
        return {}
    if isinstance(style_node, NodeDocument):
        return copy.deepcopy(style_node.renderers.get(backend, {}) or {})
    renderers = style_node.get("renderers")
    if isinstance(renderers, dict):
        payload = renderers.get(backend)
        if isinstance(payload, dict):
            return copy.deepcopy(payload)
    payload = style_node.get(backend)
    if isinstance(payload, dict):
        return copy.deepcopy(payload)
    return copy.deepcopy(style_node)


def renderer_style_prompt_parts(
    style_node: NodeDocument | dict[str, Any] | None,
    backend: str,
) -> dict[str, list[str]]:
    if style_node is None:
        return {
            "prompt_prefix": [],
            "prompt_suffix": [],
            "negative_prompt": [],
            "after_negative_prompt": [],
        }

    payload = renderer_style_payload(style_node, backend)
    include_common = payload.get("include_common_tags", True)
    common_positive, common_negative = _common_style_prompt_parts(style_node)

    prompt_prefix = _as_string_list(payload.get("prompt_prefix"))
    prompt_suffix = _as_string_list(payload.get("prompt_suffix"))
    negative_prompt = _as_string_list(payload.get("negative_prompt"))
    after_negative_prompt = _as_string_list(payload.get("after_negative_prompt"))

    if include_common:
        prompt_suffix = common_positive + prompt_suffix
        negative_prompt = common_negative + negative_prompt

    return {
        "prompt_prefix": prompt_prefix,
        "prompt_suffix": prompt_suffix,
        "negative_prompt": negative_prompt,
        "after_negative_prompt": after_negative_prompt,
    }


def render_meta(bundle: PromptBundle, *, action: str, backend: str) -> dict[str, Any]:
    return {
        "action": action,
        "backend": backend,
        "style_ref": bundle.meta.style_ref,
        "composer_type": bundle.meta.composer_type,
        "composer_version": bundle.meta.composer_version,
        "prompt_cache_key": bundle.cache.cache_key,
    }


def get_setting(
    params: dict[str, Any],
    style_payload: dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    return params[key] if key in params else style_payload.get(key, default)


def preserve_extra_params(
    params: dict[str, Any],
    *,
    reserved: set[str],
) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key not in reserved}


def _common_style_prompt_parts(
    style_node: NodeDocument | dict[str, Any],
) -> tuple[list[str], list[str]]:
    if isinstance(style_node, NodeDocument):
        positive = style_node.all_tags() + style_node.positive_texts()
        negative = style_node.negative_prompt + style_node.negative_texts()
        return positive, negative

    tags = style_node.get("tags") if isinstance(style_node, dict) else None
    positive: list[str] = []
    if isinstance(tags, dict):
        for value in tags.values():
            positive.extend(_as_string_list(value))
    else:
        positive.extend(_as_string_list(tags))

    prompt = style_node.get("prompt") if isinstance(style_node, dict) else None
    if isinstance(prompt, dict):
        positive.extend(_as_string_list(prompt.get("positive")))
        negative = _as_string_list(prompt.get("negative"))
    else:
        positive.extend(_as_string_list(prompt))
        negative = []
    negative.extend(_as_string_list(style_node.get("negative_prompt")))
    return positive, negative


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip(" ,")
        return [text] if text else []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(_as_string_list(item))
        return items
    text = str(value).strip(" ,")
    return [text] if text else []
