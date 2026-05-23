from __future__ import annotations

from typing import Any

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.contracts import PromptBundle, RenderRequest
from tags_machine_core.renderers import NovelAIRenderAdapter
from tags_machine_core.renderers.novelai_style import NovelAIStyle


class GenerationService:
    def __init__(
        self,
        composer: ScriptComposer | None = None,
        novelai_adapter: NovelAIRenderAdapter | None = None,
    ):
        self.composer = composer or ScriptComposer()
        self.novelai_adapter = novelai_adapter or NovelAIRenderAdapter()

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

    def build_novelai_request(
        self,
        bundle: PromptBundle,
        seed: int | None = None,
        style: NovelAIStyle | None = None,
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
        )
