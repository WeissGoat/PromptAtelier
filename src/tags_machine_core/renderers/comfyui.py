from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from tags_machine_core.contracts import PromptBundle, RenderRequest, RenderSize
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.renderers.common import (
    preserve_extra_params,
    render_meta,
    renderer_artist_payload,
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
            artist=artist,
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
        artist: NodeDocument | dict[str, Any] | None,
        artist_payload: dict[str, Any],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        checkpoint = (
            model
            or params.get("checkpoint")
            or params.get("model")
            or artist_payload.get("checkpoint")
            or artist_payload.get("model")
            or "default_comfy_checkpoint"
        )
        workflow, workflow_json = self._resolve_workflow(
            artist=artist,
            artist_payload=artist_payload,
            params=params,
        )
        final_params: dict[str, Any] = {
            "workflow": workflow,
            "checkpoint": checkpoint,
            "positive_prompt": bundle.prompt.positive,
            "negative_prompt": bundle.prompt.negative,
            "seed": seed if seed is not None else params.get("seed", 0),
            "width": width,
            "height": height,
            "steps": params.get("steps", artist_payload.get("steps", 28)),
            "cfg": params.get("cfg", params.get("cfg_scale", artist_payload.get("cfg", 7.0))),
            "sampler": params.get("sampler", artist_payload.get("sampler", "euler")),
            "scheduler": params.get("scheduler", artist_payload.get("scheduler", "normal")),
            "loras": params.get("loras", artist_payload.get("loras", [])),
            "embeddings": params.get("embeddings", artist_payload.get("embeddings", [])),
            "control": params.get("control", artist_payload.get("control", {})),
            "node_overrides": params.get(
                "node_overrides",
                artist_payload.get("node_overrides", {}),
            ),
        }
        if workflow_json is not None:
            final_params["workflow_json"] = workflow_json
        final_params["node_overrides"] = self._resolve_node_override_templates(
            final_params["node_overrides"],
            final_params,
        )
        final_params.update(
            preserve_extra_params(
                params,
                reserved=set(final_params)
                | {
                    "model",
                    "cfg_scale",
                    "workflow_path",
                    "workflow_template_path",
                    "workflow_template",
                },
            )
        )
        return final_params

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
