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
