from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping

from tags_machine_core.contracts import GenerationResult, PromptBundle, RenderRequest
from tags_machine_core.json_tools import to_jsonable
from tags_machine_core.nodes import NodeReader
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.services.generation_service import GenerationService

GenerationExecutor = Callable[[RenderRequest, Mapping[str, Any]], GenerationResult | Mapping[str, Any]]


class GenerationJsonApi:
    """面向前端、worker 和 CLI 的轻量 JSON 边界，不负责 HTTP 传输。"""

    def __init__(
        self,
        *,
        service: GenerationService | None = None,
        node_reader: NodeReader | None = None,
        generation_executor: GenerationExecutor | None = None,
    ):
        self.service = service or GenerationService()
        self.node_reader = node_reader or NodeReader()
        self.generation_executor = generation_executor

    def compose(self, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _mapping(request, "compose request")
        style_node = self._load_optional_node(data.get("style") or data.get("style_node"))
        style_ref = _optional_string(data.get("style_ref")) or (style_node.id if style_node else None)

        has_node_input = bool(data.get("nodes") or data.get("character") or data.get("action") or data.get("background"))
        if "prompt" in data and not has_node_input:
            bundle = self.service.compose_full_prompt(
                prompt=str(data.get("prompt") or ""),
                negative=str(data.get("negative") or ""),
                style_ref=style_ref,
            )
            return to_jsonable(bundle)

        nodes = _mapping(data.get("nodes") or {}, "compose request nodes")
        character = self._load_optional_node(nodes.get("character") or data.get("character"))
        action = self._load_optional_node(nodes.get("action") or data.get("action"))
        background = self._load_optional_node(nodes.get("background") or data.get("background"))
        if character is None and action is None and background is None and "prompt" not in data:
            raise ValueError("compose request must provide prompt or at least one node")

        bundle = self.service.compose_nodes(
            character=character,
            action=action,
            background=background,
            extra_prompt=str(data.get("extra_prompt") or data.get("prompt") or ""),
            negative=str(data.get("negative") or ""),
            style_ref=style_ref,
            character_scope=_optional_string(data.get("character_scope")),
            body_scope=_optional_string(data.get("body_scope")),
        )
        return to_jsonable(bundle)

    def render_plan(self, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _mapping(request, "render-plan request")
        bundle_data = data.get("prompt_bundle") or data.get("bundle")
        if bundle_data is None:
            raise ValueError("render-plan request must include prompt_bundle")
        bundle = PromptBundle.model_validate(bundle_data)
        backend = str(data.get("backend") or "novelai")
        style = self._load_optional_node(data.get("style") or data.get("style_node"))
        request_model = self.service.build_render_request(
            bundle,
            backend=backend,
            seed=_optional_int(data.get("seed")),
            style=style or _optional_mapping(data.get("style_payload")),
            width=_int_or_default(data.get("width"), 1024),
            height=_int_or_default(data.get("height"), 1024),
            model=_optional_string(data.get("model")),
            action=str(data.get("action") or _default_render_action(backend)),
            params=dict(_optional_mapping(data.get("params")) or {}),
        )
        return to_jsonable(request_model)

    def compose_render_plan(self, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _mapping(request, "compose-render-plan request")
        compose_request = _mapping(data.get("compose") or data, "compose request")
        render_request = dict(_mapping(data.get("render") or {}, "render request"))
        if (
            "style" not in render_request
            and "style_node" not in render_request
            and "style_payload" not in render_request
        ):
            if "style" in compose_request:
                render_request["style"] = compose_request["style"]
            elif "style_node" in compose_request:
                render_request["style_node"] = compose_request["style_node"]
        bundle = self.compose(compose_request)
        render_request["prompt_bundle"] = bundle
        return {
            "schema": "tags-machine-core.compose-render-plan-result/v1",
            "prompt_bundle": bundle,
            "render_request": self.render_plan(render_request),
        }

    def generate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        data = _mapping(request, "generate request")
        request_data = data.get("render_request") or data.get("request")
        if request_data is None:
            raise ValueError("generate request must include render_request")
        render_request = RenderRequest.model_validate(request_data)
        if self.generation_executor is None:
            raise ValueError("generate request requires a generation_executor")
        result = self.generation_executor(render_request, data)
        if isinstance(result, GenerationResult):
            return to_jsonable(result)
        return to_jsonable(GenerationResult.model_validate(result))

    def _load_optional_node(self, value: Any) -> NodeDocument | None:
        if value is None or value == "":
            return None
        if isinstance(value, NodeDocument):
            return value
        if isinstance(value, (str, Path)):
            return self.node_reader.read(value)
        if isinstance(value, Mapping):
            return NodeDocument.model_validate(value)
        raise ValueError(f"Expected node path or node mapping, got: {type(value).__name__}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise ValueError(f"Expected mapping for {label}")


def _optional_mapping(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    return _mapping(value, "optional mapping")


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _int_or_default(value: Any, default: int) -> int:
    return default if value is None or value == "" else int(value)


def _default_render_action(backend: str) -> str:
    return "generate" if backend == "novelai" else "render-plan"
