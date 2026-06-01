from __future__ import annotations

import copy
from typing import Any

from tags_machine_core.contracts import PromptBundle
from tags_machine_core.nodes.models import NodeDocument


def renderer_artist_payload(
    artist_node: NodeDocument | dict[str, Any] | None,
    backend: str,
) -> dict[str, Any]:
    if artist_node is None:
        return {}
    if isinstance(artist_node, NodeDocument):
        return copy.deepcopy(artist_node.renderers.get(backend, {}) or {})
    renderers = artist_node.get("renderers")
    if isinstance(renderers, dict):
        payload = renderers.get(backend)
        if isinstance(payload, dict):
            return copy.deepcopy(payload)
    payload = artist_node.get(backend)
    if isinstance(payload, dict):
        return copy.deepcopy(payload)
    return copy.deepcopy(artist_node)


def renderer_artist_prompt_parts(
    artist_node: NodeDocument | dict[str, Any] | None,
    backend: str,
) -> dict[str, list[str]]:
    if artist_node is None:
        return {
            "prompt_prefix": [],
            "prompt_suffix": [],
            "negative_prompt": [],
            "after_negative_prompt": [],
        }

    payload = renderer_artist_payload(artist_node, backend)
    include_common = payload.get("include_common_tags", True)
    common_positive, common_negative = _common_artist_prompt_parts(artist_node)

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
        "composer_type": bundle.meta.composer_type,
        "composer_version": bundle.meta.composer_version,
        "prompt_cache_key": bundle.cache.cache_key,
    }


def get_setting(
    params: dict[str, Any],
    artist_payload: dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    return params[key] if key in params else artist_payload.get(key, default)


def preserve_extra_params(
    params: dict[str, Any],
    *,
    reserved: set[str],
) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key not in reserved}


def _common_artist_prompt_parts(
    artist_node: NodeDocument | dict[str, Any],
) -> tuple[list[str], list[str]]:
    if isinstance(artist_node, NodeDocument):
        positive = artist_node.all_tags() + artist_node.positive_texts()
        negative = artist_node.negative_prompt + artist_node.negative_texts()
        return positive, negative

    tags = artist_node.get("tags") if isinstance(artist_node, dict) else None
    positive: list[str] = []
    if isinstance(tags, dict):
        for value in tags.values():
            positive.extend(_as_string_list(value))
    else:
        positive.extend(_as_string_list(tags))

    prompt = artist_node.get("prompt") if isinstance(artist_node, dict) else None
    if isinstance(prompt, dict):
        positive.extend(_as_string_list(prompt.get("positive")))
        negative = _as_string_list(prompt.get("negative"))
    else:
        positive.extend(_as_string_list(prompt))
        negative = []
    negative.extend(_as_string_list(artist_node.get("negative_prompt")))
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
