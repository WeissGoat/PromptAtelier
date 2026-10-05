from __future__ import annotations

import copy
import json
from pathlib import Path
import random
from typing import Any

from tags_machine_core.contracts import PromptBundle, RenderRequest, RenderSize
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.renderers.common import (
    preserve_extra_params,
    render_meta,
    renderer_artist_payload,
)
from tags_machine_core.renderers.comfyui_prompt import novelai_to_comfyui_prompt
from tags_machine_core.renderers.sizes import resolve_render_size
from tags_machine_core.renderers.comfyui_workflow import (
    build_bound_overrides,
    check_override_paths,
    optional_input_paths,
    output_node_ids,
    required_input_paths,
    validate_api_workflow,
    workflow_hash,
)


# prompt_format 是 workflow 期望的提示词写法：
# comfyui（默认）由这里把 NovelAI 写法转成 ComfyUI 写法；novelai 原样传入，由 workflow 自己转换。
PROMPT_FORMATS = ("comfyui", "novelai")
_SEED_RANDOM = random.SystemRandom()
_RANDOM_SEED_MAX = 4294967295


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
        artist: NodeDocument | dict[str, Any] | None = None,
    ) -> RenderRequest:
        artist_payload = renderer_artist_payload(artist, self.backend)
        artist_params = copy.deepcopy(artist_payload.get("params", {}) or {})
        # params.size（random / portrait / landscape / square / custom）按画风的预设定宽高，见 renderers/sizes.py。
        width, height, size_preset, merged_params = resolve_render_size(
            artist_payload,
            {**artist_params, **(params or {})},
            width=width,
            height=height,
            rng=_SEED_RANDOM,
        )
        resolved_model = (
            model
            or artist_payload.get("model")
            or artist_payload.get("checkpoint")
        )
        final_params = self._build_parameters(
            bundle=bundle,
            seed=seed,
            width=width,
            height=height,
            model=resolved_model,
            artist=artist,
            artist_payload=artist_payload,
            params=merged_params,
        )
        meta = render_meta(bundle, action=action, backend=self.backend)
        if size_preset is not None:
            meta["size_preset"] = size_preset
        return RenderRequest(
            backend=self.backend,
            prompt=bundle.prompt.positive,
            negative_prompt=bundle.prompt.negative,
            model=resolved_model,
            seed=final_params["seed"],
            size=RenderSize(width=width, height=height),
            params=final_params,
            artist_payload=artist_payload,
            meta=meta,
        )

    def _build_parameters(
        self,
        *,
        bundle: PromptBundle,
        seed: int | None,
        width: int,
        height: int,
        model: str | None,
        artist: NodeDocument | dict[str, Any] | None,
        artist_payload: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        workflow, workflow_json = self._resolve_workflow(
            artist=artist,
            artist_payload=artist_payload,
            params=params,
        )
        if workflow_json is None:
            raise ValueError(
                "ComfyUI renderer requires renderers.comfyui.workflow_json or workflow_path"
            )
        validate_api_workflow(workflow_json, source=str(workflow))
        workflow_ui_json = self._resolve_workflow_ui_json(
            artist=artist,
            artist_payload=artist_payload,
            params=params,
        )

        seed_value = seed if seed is not None else params.get("seed")
        # 没给 seed 或给了负数（Web 的 -1）都表示随机，和 NovelAI 渲染层一致；
        # 抽到的 seed 写进请求，归档和 PNG 里看到的就是实际用的值。
        if seed_value is None or (isinstance(seed_value, int) and seed_value < 0):
            seed_value = _SEED_RANDOM.randint(0, _RANDOM_SEED_MAX)
        input_paths = required_input_paths(artist_payload)
        optional_paths = optional_input_paths(artist_payload)
        output_nodes = output_node_ids(artist_payload)
        prompt_format = str(
            params.get("prompt_format") or artist_payload.get("prompt_format") or "comfyui"
        )
        if prompt_format not in PROMPT_FORMATS:
            raise ValueError(
                f"ComfyUI prompt_format must be one of {', '.join(PROMPT_FORMATS)}, got {prompt_format!r}"
            )
        positive_prompt = bundle.prompt.positive
        negative_prompt = bundle.prompt.negative
        if prompt_format == "comfyui":
            positive_prompt = novelai_to_comfyui_prompt(positive_prompt)
            negative_prompt = novelai_to_comfyui_prompt(negative_prompt)
        semantic_values = {
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "seed": seed_value,
        }
        optional_values = self._explicit_optional_values(params)
        template_context = {
            **semantic_values,
            **optional_values,
            "workflow": workflow,
        }
        explicit_overrides = self._resolve_node_override_templates(
            params.get("node_overrides", artist_payload.get("node_overrides", {})),
            template_context,
        )
        if not isinstance(explicit_overrides, dict):
            raise ValueError("ComfyUI node_overrides must be a mapping")
        node_overrides: dict[str, Any] = dict(explicit_overrides)
        node_overrides.update(
            build_bound_overrides(
                inputs=input_paths,
                values=semantic_values,
                source="renderers.comfyui.inputs",
            )
        )
        node_overrides.update(
            build_bound_overrides(
                inputs=optional_paths,
                values=optional_values,
                source="renderers.comfyui.optional_inputs",
            )
        )
        strict_bindings = params.get("strict_bindings", artist_payload.get("strict_bindings", True))
        if strict_bindings is not False:
            check_override_paths(workflow_json, node_overrides, source=f"workflow {workflow}")

        final_params: dict[str, Any] = {
            "workflow": workflow,
            "workflow_json": workflow_json,
            "workflow_hash": workflow_hash(workflow_json),
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "prompt_format": prompt_format,
            "seed": seed_value,
            "width": width,
            "height": height,
            "node_overrides": node_overrides,
            "comfyui_inputs": {
                "inputs": copy.deepcopy(input_paths),
                "optional_inputs": copy.deepcopy(optional_paths),
            },
        }
        if workflow_ui_json is not None:
            final_params["workflow_ui_json"] = workflow_ui_json
            final_params["extra_pnginfo"] = {"workflow": workflow_ui_json}
        if output_nodes:
            final_params["output_nodes"] = output_nodes
        if strict_bindings is False:
            final_params["strict_bindings"] = False
        input_files = self._resolve_input_files(
            artist=artist,
            artist_payload=artist_payload,
            params=params,
        )
        if input_files:
            final_params["input_files"] = input_files
        final_params.update(optional_values)
        final_params.update(
            preserve_extra_params(
                params,
                reserved=set(final_params)
                | {
                    "checkpoint",
                    "model",
                    "cfg_scale",
                    "inputs",
                    "optional_inputs",
                    "output_nodes",
                    "node_overrides",
                    "workflow_path",
                    "workflow_template_path",
                    "workflow_template",
                    "workflow_json",
                    "workflow_ui_path",
                    "workflow_ui_json",
                    "extra_pnginfo",
                    "input_files",
                    "strict_bindings",
                },
            )
        )
        return final_params

    def _resolve_input_files(
        self,
        *,
        artist: NodeDocument | dict[str, Any] | None,
        artist_payload: dict[str, Any],
        params: dict[str, Any],
    ) -> list[dict[str, str]]:
        """LoadImage 等节点要用的输入图；提交前会上传到目标 ComfyUI 的 input 目录。"""
        value = params["input_files"] if "input_files" in params else artist_payload.get("input_files")
        if not value:
            return []
        if not isinstance(value, list):
            raise ValueError("ComfyUI input_files must be a list")
        resolved: list[dict[str, str]] = []
        for index, item in enumerate(value):
            if isinstance(item, str):
                item = {"path": item}
            if not isinstance(item, dict) or not item.get("path"):
                raise ValueError(f"ComfyUI input_files[{index}] requires a path")
            path = self._resolve_workflow_path(item["path"], artist)
            entry = {"name": str(item.get("name") or path.name), "path": str(path)}
            if item.get("subfolder"):
                entry["subfolder"] = str(item["subfolder"])
            resolved.append(entry)
        return resolved

    def _explicit_optional_values(self, params: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key in ("steps", "cfg", "sampler", "scheduler"):
            if key in params:
                values[key] = params[key]
        if "cfg" not in values and "cfg_scale" in params:
            values["cfg"] = params["cfg_scale"]
        return values

    def _resolve_workflow(
        self,
        *,
        artist: NodeDocument | dict[str, Any] | None,
        artist_payload: dict[str, Any],
        params: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | None]:
        inline_workflow = (
            params["workflow_json"]
            if "workflow_json" in params
            else artist_payload.get("workflow_json")
        )
        if inline_workflow is not None:
            if not isinstance(inline_workflow, dict):
                raise ValueError("ComfyUI workflow_json must be a mapping")
            workflow_label = params.get("workflow") or artist_payload.get("workflow") or "inline"
            return str(workflow_label), copy.deepcopy(inline_workflow)

        workflow_path = (
            params.get("workflow_path")
            or params.get("workflow_template_path")
            or artist_payload.get("workflow_path")
            or artist_payload.get("workflow_template_path")
        )
        workflow_label = (
            params.get("workflow")
            or params.get("workflow_template")
            or artist_payload.get("workflow")
            or artist_payload.get("workflow_template")
            or (Path(str(workflow_path)).stem if workflow_path else "default")
        )
        if workflow_path:
            path = self._resolve_workflow_path(workflow_path, artist)
            return str(workflow_label), self._load_workflow_json(path)
        return str(workflow_label), None

    def _resolve_workflow_ui_json(
        self,
        *,
        artist: NodeDocument | dict[str, Any] | None,
        artist_payload: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        inline_workflow = (
            params["workflow_ui_json"]
            if "workflow_ui_json" in params
            else artist_payload.get("workflow_ui_json")
        )
        if inline_workflow is not None:
            if not isinstance(inline_workflow, dict):
                raise ValueError("ComfyUI workflow_ui_json must be a mapping")
            return copy.deepcopy(inline_workflow)

        workflow_path = params.get("workflow_ui_path") or artist_payload.get("workflow_ui_path")
        if not workflow_path:
            return None
        path = self._resolve_workflow_path(workflow_path, artist)
        return self._load_workflow_json(path)

    def _resolve_workflow_path(
        self,
        value: str | Path,
        artist: NodeDocument | dict[str, Any] | None,
    ) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        if isinstance(artist, NodeDocument) and artist.path is not None:
            return artist.path / path
        return path

    def _load_workflow_json(self, path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"ComfyUI workflow JSON must be a mapping: {path}")
        return data

    def _resolve_node_override_templates(
        self,
        value: Any,
        context: dict[str, Any],
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: self._resolve_node_override_templates(item, context)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._resolve_node_override_templates(item, context) for item in value]
        if not isinstance(value, str):
            return value

        if value.startswith("{") and value.endswith("}") and value.count("{") == 1:
            key = value[1:-1]
            if key in context:
                return context[key]

        resolved = value
        for key, item in context.items():
            if isinstance(item, (dict, list)):
                continue
            resolved = resolved.replace(f"{{{key}}}", str(item))
        return resolved
