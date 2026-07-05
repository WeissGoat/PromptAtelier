from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tags_machine_core.composers import AgentCompositionRequired, load_agent_result
from tags_machine_core.composers.cache import PromptCache
from tags_machine_core.config import AppConfig
from tags_machine_core.contracts import GenerationResult, PromptBundle, RenderRequest
from tags_machine_core.execution import execute_mock_generation, execute_render_request
from tags_machine_core.nodes import NodeReader, NovelAIArtistRepository, ResolvedNode, ResolvedNodeSet
from tags_machine_core.services import GenerationService

from .models import BatchTask


class BatchExecutionResult(BaseModel):
    status: str
    prompt_bundle: PromptBundle | None = None
    render_request: RenderRequest | None = None
    generation_result: GenerationResult | None = None
    agent_task: Any | None = None
    image_paths: list[str] = Field(default_factory=list)
    error: str | None = None


class BatchExecutor:
    def __init__(
        self,
        *,
        service: GenerationService | None = None,
        node_reader: NodeReader | None = None,
    ):
        self.service = service or GenerationService()
        self.node_reader = node_reader or NodeReader()

    def execute(
        self,
        task: BatchTask,
        *,
        config: AppConfig,
        output_dir: str | Path | None = None,
        mock: bool = False,
    ) -> BatchExecutionResult:
        resolved_nodes = self._resolved_nodes(task, config=config)
        try:
            bundle = self._compose(task, resolved_nodes)
        except AgentCompositionRequired as exc:
            return BatchExecutionResult(status="requires_agent", agent_task=exc.task)
        artist_node = resolved_nodes.first("artist")
        render_params = dict(task.render.params)
        render_params["n_samples"] = task.render.nt
        request = self.service.build_render_request(
            bundle,
            backend=task.render.backend,
            seed=task.render.seed,
            artist=artist_node.node if artist_node else None,
            resolved_nodes=resolved_nodes,
            width=task.render.width or 1024,
            height=task.render.height or 1024,
            model=task.render.model if task.render.backend == "novelai" else None,
            action="generate" if task.render.backend == "novelai" else "render-plan",
            params=render_params,
        )
        if mock:
            generation = execute_mock_generation(
                request,
                output_dir=output_dir or task.render.output_dir,
                image_format=task.render.image_format,
            )
        else:
            generation = execute_render_request(
                config,
                request,
                output_dir=output_dir or task.render.output_dir,
                image_format=task.render.image_format,
                allow_experimental_backend=False,
            )
        return BatchExecutionResult(
            status="succeeded",
            prompt_bundle=bundle,
            render_request=request,
            generation_result=generation,
            image_paths=[str(image.path) for image in generation.images],
        )

    def _compose(self, task: BatchTask, resolved_nodes: ResolvedNodeSet) -> PromptBundle:
        if task.composer == "full":
            return self.service.compose_full_prompt(
                prompt=task.prompt or "",
                negative=task.negative or "",
                prompt_policy=task.policy or None,
            )
        if task.composer == "agent":
            cache = PromptCache(task.agent.cache_dir) if task.agent.cache_dir else None
            result = self._agent_result_for_task(task)
            task_negative = task.negative or ""
            if task.prompt and result is None:
                result = {
                    "positive": task.prompt,
                    "negative": task_negative,
                }
                task_negative = ""
            return self.service.compose_resolved_nodes_with_agent(
                resolved_nodes,
                extra_prompt=task.extra_prompt,
                negative=task_negative,
                agent_model=task.agent.agent_model,
                result=result,
                cache=cache,
            )
        return self.service.compose_resolved_nodes(
            resolved_nodes,
            extra_prompt=task.extra_prompt,
            negative=task.negative or "",
            prompt_policy=task.policy or None,
        )

    def _resolved_nodes(self, task: BatchTask, *, config: AppConfig) -> ResolvedNodeSet:
        nodes = list(task.nodes)
        if task.render.artist and not any(node.role == "artist" for node in nodes):
            from .models import NodeRef

            nodes.append(NodeRef(role="artist", ref=task.render.artist, index=0))

        artist_repo = NovelAIArtistRepository(config.legacy.design_root)
        items: list[ResolvedNode] = []
        role_counts: dict[str, int] = {}
        for node_ref in nodes:
            index = role_counts.get(node_ref.role, 0)
            role_counts[node_ref.role] = index + 1
            if node_ref.role == "artist":
                document = (
                    self.node_reader.read(node_ref.ref)
                    if Path(node_ref.ref).exists() or task.render.backend != "novelai"
                    else artist_repo.load_node(node_ref.ref)
                )
            else:
                document = self.node_reader.read(node_ref.ref)
            items.append(
                ResolvedNode(
                    role=node_ref.role,
                    ref=node_ref.ref,
                    index=index,
                    node=document,
                )
            )
        return ResolvedNodeSet(items)

    def _agent_result_for_task(self, task: BatchTask):
        for path in self._agent_result_paths(task):
            if path.exists():
                return load_agent_result(path)
        return None

    def _agent_result_paths(self, task: BatchTask) -> list[Path]:
        task_dir = Path(task.output.task_dir)
        paths = [task_dir / "agent_result.json"]
        try:
            run_dir = task_dir.parents[1]
        except IndexError:
            return paths
        paths.append(run_dir / "agent_results" / f"{task.id}.json")
        return paths
