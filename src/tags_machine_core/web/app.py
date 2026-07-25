from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tags_machine_core.contracts import GenerationResult, RenderRequest
from tags_machine_core.config import build_prompt_policy_provider, load_config
from tags_machine_core.execution import execute_render_request
from tags_machine_core.nodes.novelai_artist import NovelAIArtistRepository
from tags_machine_core.services import GenerationJsonApi
from tags_machine_core.services.generation_service import GenerationService
from tags_machine_core.services.json_api import GenerationExecutor

from .errors import ApiError, api_error_handler
from .routes import batch, compose, generate, health, jobs, node_pools, nodes, results
from .services.batch_workspace import BatchWorkspace
from .services.job_manager import JobManager
from .services.node_workspace import NodeWorkspace
from .services.node_pool_service import NodePoolService
from .services.node_save_preview_store import NodeSavePreviewStore
from .services.result_index import ResultIndex


DEFAULT_LOCAL_CONFIG = Path("configs/local.yaml")
DEFAULT_EXAMPLE_CONFIG = Path("configs/local.example.yaml")
CONFIG_ENV_VAR = "TAGS_MACHINE_CONFIG"


def resolve_web_config_path(config_path: str | Path | None = None) -> Path:
    """解析 Web 默认配置路径：显式参数 > 环境变量 > 本地配置 > 示例配置。"""
    if config_path:
        return Path(config_path)
    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path:
        return Path(env_path)
    if DEFAULT_LOCAL_CONFIG.exists():
        return DEFAULT_LOCAL_CONFIG
    return DEFAULT_EXAMPLE_CONFIG


def create_app(
    *,
    job_manager: JobManager | None = None,
    node_workspace: NodeWorkspace | None = None,
    result_index: ResultIndex | None = None,
    batch_workspace: BatchWorkspace | None = None,
    generation_executor: GenerationExecutor | None = None,
    config_path: str | Path | None = None,
) -> FastAPI:
    resolved_config_path = resolve_web_config_path(config_path)
    config = load_config(resolved_config_path)
    app = FastAPI(title="PromptAtelier Web Console", version="0.1.0")
    app.state.job_manager = job_manager or JobManager()
    app.state.config = config
    app.state.config_path = resolved_config_path
    app.state.node_workspace = node_workspace or NodeWorkspace(design_root=config.legacy.design_root)
    app.state.node_pool_service = NodePoolService(
        workspace=app.state.node_workspace,
        project_requires=config.web.project_requires,
        base_dir=Path.cwd(),
    )
    app.state.node_save_previews = NodeSavePreviewStore()
    app.state.result_index = result_index or ResultIndex(
        roots=[config.runtime.output_dir, "outputs", "examples/batches/outputs"],
    )
    app.state.batch_workspace = batch_workspace or BatchWorkspace(base_dir=Path.cwd())
    policy_provider = build_prompt_policy_provider(
        config,
        config_path=resolved_config_path,
    )
    app.state.generation_api = GenerationJsonApi(
        service=GenerationService(policy_provider=policy_provider),
        artist_loader=NovelAIArtistRepository(config.legacy.design_root).load_node,
        generation_executor=generation_executor or _default_generation_executor(config),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(jobs.router, prefix="/api", tags=["jobs"])
    app.include_router(nodes.router, prefix="/api", tags=["nodes"])
    app.include_router(node_pools.router, prefix="/api", tags=["node-pools"])
    app.include_router(compose.router, prefix="/api", tags=["compose"])
    app.include_router(generate.router, prefix="/api", tags=["generate"])
    app.include_router(results.router, prefix="/api", tags=["results"])
    app.include_router(batch.router, prefix="/api", tags=["batch"])
    return app


def _default_generation_executor(config) -> GenerationExecutor:
    def executor(
        request: RenderRequest,
        options: Mapping[str, Any],
    ) -> GenerationResult:
        return execute_render_request(
            config,
            request,
            output_dir=options.get("output_dir"),
            image_format=str(options.get("image_format") or config.defaults.image_format),
        )

    return executor
