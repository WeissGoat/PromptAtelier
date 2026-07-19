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
from tags_machine_core.logging_config import get_logger
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet
from tags_machine_core.nodes.novelai_artist import NovelAIArtist
from tags_machine_core.policies import (
    PromptPolicyConfig,
    PromptPolicyPipeline,
    PromptPolicyProvider,
    PromptPolicySource,
)
from tags_machine_core.renderers import ComfyUIRenderAdapter, NovelAIRenderAdapter, SDRenderAdapter


logger = get_logger(__name__)


class GenerationService:
    def __init__(
        self,
        composer: ScriptComposer | None = None,
        agent_composer: AgentComposer | None = None,
        novelai_adapter: NovelAIRenderAdapter | None = None,
        comfyui_adapter: ComfyUIRenderAdapter | None = None,
        sd_adapter: SDRenderAdapter | None = None,
        policy_pipeline: PromptPolicyPipeline | None = None,
        policy_provider: PromptPolicyProvider | None = None,
    ):
        self.composer = composer or ScriptComposer()
        self.agent_composer = agent_composer or AgentComposer()
        self.novelai_adapter = novelai_adapter or NovelAIRenderAdapter()
        self.comfyui_adapter = comfyui_adapter or ComfyUIRenderAdapter()
        self.sd_adapter = sd_adapter or SDRenderAdapter()
        self.policy_pipeline = policy_pipeline or PromptPolicyPipeline()
        self.policy_provider = policy_provider or PromptPolicyProvider.with_builtin_defaults()

    def compose_full_prompt(
        self,
        prompt: str,
        negative: str = "",
        prompt_policy: PromptPolicyConfig | PromptPolicySource | dict[str, Any] | None = None,
    ) -> PromptBundle:
        bundle = self.composer.compose_full_prompt(
            prompt=prompt,
            negative=negative,
        )
        logger.info(
            "compose_full_prompt produced bundle composer=%s positive_chars=%s",
            bundle.meta.composer_type,
            len(bundle.prompt.positive),
        )
        return self.policy_pipeline.apply(
            bundle,
            config=self.policy_provider.resolve(prompt_policy),
            target="full_prompt",
        )

    def compose_nodes(
        self,
        *,
        character: NodeDocument | None = None,
        action: NodeDocument | None = None,
        background: NodeDocument | None = None,
        artist: NodeDocument | None = None,
        extra_prompt: str = "",
        negative: str = "",
        character_scope: str | None = None,
        body_scope: str | None = None,
        identity_minimal_sections: list[str] | None = None,
        prompt_policy: PromptPolicyConfig | PromptPolicySource | dict[str, Any] | None = None,
    ) -> PromptBundle:
        bundle = self.composer.compose_nodes(
            character=character,
            action=action,
            background=background,
            artist=artist,
            extra_prompt=extra_prompt,
            negative=negative,
            character_scope=character_scope,
            body_scope=body_scope,
            identity_minimal_sections=identity_minimal_sections,
        )
        logger.info(
            "compose_nodes produced bundle composer=%s node_count=%s",
            bundle.meta.composer_type,
            len(bundle.meta.nodes),
        )
        resolved_nodes = ResolvedNodeSet(
            [
                ResolvedNode(role=role, ref=node.source_ref(), index=0, node=node)
                for role, node in (
                    ("character", character),
                    ("action", action),
                    ("background", background),
                    ("artist", artist),
                )
                if node is not None
            ]
        )
        return self.policy_pipeline.apply(
            bundle,
            resolved_nodes=resolved_nodes,
            config=self.policy_provider.resolve(prompt_policy),
            target="script",
        )

    def compose_resolved_nodes(
        self,
        resolved_nodes: ResolvedNodeSet,
        *,
        extra_prompt: str = "",
        negative: str = "",
        character_scope: str | None = None,
        body_scope: str | None = None,
        identity_minimal_sections: list[str] | None = None,
        prompt_policy: PromptPolicyConfig | PromptPolicySource | dict[str, Any] | None = None,
    ) -> PromptBundle:
        bundle = self.composer.compose_resolved_nodes(
            resolved_nodes,
            extra_prompt=extra_prompt,
            negative=negative,
            character_scope=character_scope,
            body_scope=body_scope,
            identity_minimal_sections=identity_minimal_sections,
        )
        logger.info(
            "compose_resolved_nodes produced bundle composer=%s resolved_node_count=%s",
            bundle.meta.composer_type,
            len(resolved_nodes),
        )
        return self.policy_pipeline.apply(
            bundle,
            resolved_nodes=resolved_nodes,
            config=self.policy_provider.resolve(prompt_policy),
            target="script",
        )

    def build_agent_composition_task(
        self,
        *,
        character: NodeDocument | None = None,
        action: NodeDocument | None = None,
        background: NodeDocument | None = None,
        artist: NodeDocument | None = None,
        extra_prompt: str = "",
        negative: str = "",
        character_scope: str | None = None,
        instructions: list[str] | None = None,
        agent_model: str | None = None,
    ) -> AgentCompositionTask:
        logger.info("build_agent_composition_task started")
        return self.agent_composer.build_task(
            character=character,
            action=action,
            background=background,
            artist=artist,
            extra_prompt=extra_prompt,
            negative=negative,
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
        character_scope: str | None = None,
        instructions: list[str] | None = None,
        agent_model: str | None = None,
    ) -> AgentCompositionTask:
        logger.info(
            "build_agent_composition_task_resolved_nodes started resolved_node_count=%s",
            len(resolved_nodes),
        )
        return self.agent_composer.build_task_resolved_nodes(
            resolved_nodes,
            extra_prompt=extra_prompt,
            negative=negative,
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
        artist: NodeDocument | None = None,
        extra_prompt: str = "",
        negative: str = "",
        character_scope: str | None = None,
        instructions: list[str] | None = None,
        agent_model: str | None = None,
        result: AgentCompositionResult | dict[str, Any] | None = None,
        cache: PromptCache | None = None,
    ) -> PromptBundle:
        logger.info(
            "compose_nodes_with_agent started; PromptPolicyPipeline bypassed by design"
        )
        return self.agent_composer.compose_nodes(
            character=character,
            action=action,
            background=background,
            artist=artist,
            extra_prompt=extra_prompt,
            negative=negative,
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
        character_scope: str | None = None,
        instructions: list[str] | None = None,
        agent_model: str | None = None,
        result: AgentCompositionResult | dict[str, Any] | None = None,
        cache: PromptCache | None = None,
    ) -> PromptBundle:
        logger.info(
            "compose_resolved_nodes_with_agent started; PromptPolicyPipeline bypassed by design"
        )
        return self.agent_composer.compose_resolved_nodes(
            resolved_nodes,
            extra_prompt=extra_prompt,
            negative=negative,
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
        artist: NovelAIArtist | NodeDocument | dict[str, Any] | None = None,
        resolved_nodes: ResolvedNodeSet | None = None,
        width: int = 1024,
        height: int = 1024,
        model: str = "nai-diffusion-4-5-full",
        action: str = "generate",
        params: dict[str, Any] | None = None,
    ) -> RenderRequest:
        logger.info(
            "build_novelai_request started model=%s size=%sx%s composer=%s",
            model,
            width,
            height,
            bundle.meta.composer_type,
        )
        return self.novelai_adapter.build_request(
            bundle,
            seed=seed,
            width=width,
            height=height,
            model=model,
            action=action,
            params=params,
            artist=artist,
            resolved_nodes=resolved_nodes,
        )

    def build_render_request(
        self,
        bundle: PromptBundle,
        *,
        backend: str = "novelai",
        seed: int | None = None,
        artist: NovelAIArtist | NodeDocument | dict[str, Any] | None = None,
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
        logger.info(
            "build_render_request started backend=%s model=%s size=%sx%s composer=%s",
            backend,
            model,
            width,
            height,
            bundle.meta.composer_type,
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
                artist=artist,
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
                artist=artist,
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
                artist=artist,
            )
        raise ValueError(f"Unsupported backend: {backend}")
