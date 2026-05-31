from __future__ import annotations

from typing import Any

from tags_machine_core.backends import ensure_backend_can_build_render_plan
from tags_machine_core.composers import (
    AgentComposer,
    AgentCompositionResult,
    AgentCompositionTask,
    ScriptComposer,
)
from tags_machine_core.composers.cache import PromptCache
from tags_machine_core.contracts import PromptBundle, RenderRequest
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNodeSet
from tags_machine_core.nodes.novelai_style import NovelAIStyle
from tags_machine_core.renderers import ComfyUIRenderAdapter, NovelAIRenderAdapter, SDRenderAdapter


class GenerationService:
    def __init__(
        self,
        composer: ScriptComposer | None = None,
        agent_composer: AgentComposer | None = None,
        novelai_adapter: NovelAIRenderAdapter | None = None,
        comfyui_adapter: ComfyUIRenderAdapter | None = None,
        sd_adapter: SDRenderAdapter | None = None,
    ):
        self.composer = composer or ScriptComposer()
        self.agent_composer = agent_composer or AgentComposer()
        self.novelai_adapter = novelai_adapter or NovelAIRenderAdapter()
        self.comfyui_adapter = comfyui_adapter or ComfyUIRenderAdapter()
        self.sd_adapter = sd_adapter or SDRenderAdapter()

    def compose_full_prompt(
        self,
        prompt: str,
        negative: str = "",
        style_ref: str | None = None,
    ) -> PromptBundle:
        return self.composer.compose_full_prompt(
            prompt=prompt,
            negative=negative,
            style_ref=style_ref,
        )

    def compose_nodes(
        self,
        *,
        character: NodeDocument | None = None,
        action: NodeDocument | None = None,
        background: NodeDocument | None = None,
        extra_prompt: str = "",
        negative: str = "",
        style_ref: str | None = None,
        character_scope: str | None = None,
        body_scope: str | None = None,
    ) -> PromptBundle:
        return self.composer.compose_nodes(
            character=character,
            action=action,
            background=background,
            extra_prompt=extra_prompt,
            negative=negative,
            style_ref=style_ref,
            character_scope=character_scope,
            body_scope=body_scope,
        )

    def compose_resolved_nodes(
        self,
        resolved_nodes: ResolvedNodeSet,
        *,
        extra_prompt: str = "",
        negative: str = "",
        style_ref: str | None = None,
        character_scope: str | None = None,
        body_scope: str | None = None,
    ) -> PromptBundle:
        return self.composer.compose_resolved_nodes(
            resolved_nodes,
            extra_prompt=extra_prompt,
            negative=negative,
            style_ref=style_ref,
            character_scope=character_scope,
            body_scope=body_scope,
        )

    def build_agent_composition_task(
        self,
        *,
        character: NodeDocument | None = None,
        action: NodeDocument | None = None,
        background: NodeDocument | None = None,
        extra_prompt: str = "",
        negative: str = "",
        style_ref: str | None = None,
        character_scope: str | None = None,
        instructions: list[str] | None = None,
        agent_model: str | None = None,
    ) -> AgentCompositionTask:
        return self.agent_composer.build_task(
            character=character,
            action=action,
            background=background,
            extra_prompt=extra_prompt,
            negative=negative,
            style_ref=style_ref,
            character_scope=character_scope,
            instructions=instructions,
            agent_model=agent_model,
        )

    def build_agent_composition_task_resolved_nodes(
        self,
        resolved_nodes: ResolvedNodeSet,
        *,
        extra_prompt: str = "",
        negative: str = "",
        style_ref: str | None = None,
        character_scope: str | None = None,
        instructions: list[str] | None = None,
        agent_model: str | None = None,
    ) -> AgentCompositionTask:
        return self.agent_composer.build_task_resolved_nodes(
            resolved_nodes,
            extra_prompt=extra_prompt,
            negative=negative,
            style_ref=style_ref,
            character_scope=character_scope,
            instructions=instructions,
            agent_model=agent_model,
        )

    def compose_nodes_with_agent(
        self,
        *,
        character: NodeDocument | None = None,
        action: NodeDocument | None = None,
        background: NodeDocument | None = None,
        extra_prompt: str = "",
        negative: str = "",
        style_ref: str | None = None,
        character_scope: str | None = None,
        instructions: list[str] | None = None,
        agent_model: str | None = None,
        result: AgentCompositionResult | dict[str, Any] | None = None,
        cache: PromptCache | None = None,
    ) -> PromptBundle:
        return self.agent_composer.compose_nodes(
            character=character,
            action=action,
            background=background,
            extra_prompt=extra_prompt,
            negative=negative,
            style_ref=style_ref,
            character_scope=character_scope,
            instructions=instructions,
            agent_model=agent_model,
            result=result,
            cache=cache,
        )

    def compose_resolved_nodes_with_agent(
        self,
        resolved_nodes: ResolvedNodeSet,
        *,
        extra_prompt: str = "",
        negative: str = "",
        style_ref: str | None = None,
        character_scope: str | None = None,
        instructions: list[str] | None = None,
        agent_model: str | None = None,
        result: AgentCompositionResult | dict[str, Any] | None = None,
        cache: PromptCache | None = None,
    ) -> PromptBundle:
        return self.agent_composer.compose_resolved_nodes(
            resolved_nodes,
            extra_prompt=extra_prompt,
            negative=negative,
            style_ref=style_ref,
            character_scope=character_scope,
            instructions=instructions,
            agent_model=agent_model,
            result=result,
            cache=cache,
        )

    def build_novelai_request(
        self,
        bundle: PromptBundle,
        seed: int | None = None,
        style: NovelAIStyle | NodeDocument | dict[str, Any] | None = None,
        resolved_nodes: ResolvedNodeSet | None = None,
        width: int = 1024,
        height: int = 1024,
        model: str = "nai-diffusion-4-5-full",
        action: str = "generate",
        params: dict[str, Any] | None = None,
    ) -> RenderRequest:
        return self.novelai_adapter.build_request(
            bundle,
            seed=seed,
            width=width,
            height=height,
            model=model,
            action=action,
            params=params,
            style=style,
            resolved_nodes=resolved_nodes,
        )

    def build_render_request(
        self,
        bundle: PromptBundle,
        *,
        backend: str = "novelai",
        seed: int | None = None,
        style: NovelAIStyle | NodeDocument | dict[str, Any] | None = None,
        resolved_nodes: ResolvedNodeSet | None = None,
        width: int = 1024,
        height: int = 1024,
        model: str | None = None,
        action: str = "render-plan",
        params: dict[str, Any] | None = None,
    ) -> RenderRequest:
        ensure_backend_can_build_render_plan(
            backend,
            entrypoint="GenerationService.build_render_request",
        )
        if backend == "novelai":
            return self.novelai_adapter.build_request(
                bundle,
                seed=seed,
                width=width,
                height=height,
                model=model or "nai-diffusion-4-5-full",
                action=action,
                params=params,
                style=style,
                resolved_nodes=resolved_nodes,
            )
        if backend == "comfyui":
            return self.comfyui_adapter.build_request(
                bundle,
                seed=seed,
                width=width,
                height=height,
                model=model,
                action=action,
                params=params,
                style=style,
            )
        if backend == "sd":
            return self.sd_adapter.build_request(
                bundle,
                seed=seed,
                width=width,
                height=height,
                model=model,
                action=action,
                params=params,
                style=style,
            )
        raise ValueError(f"Unsupported backend: {backend}")
