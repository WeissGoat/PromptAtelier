from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tags_machine_core.contracts import GenerationResult, RenderRequest
from tags_machine_core.config import load_config
from tags_machine_core.execution import execute_render_request
from tags_machine_core.services import GenerationJsonApi
from tags_machine_core.services.json_api import GenerationExecutor

from .errors import ApiError, api_error_handler
from .routes import compose, generate, health, jobs, nodes, results
from .services.job_manager import JobManager
from .services.node_workspace import NodeWorkspace
from .services.result_index import ResultIndex


def create_app(
    *,
    job_manager: JobManager | None = None,
    node_workspace: NodeWorkspace | None = None,
    result_index: ResultIndex | None = None,
    generation_executor: GenerationExecutor | None = None,
    config_path: str | Path = "configs/local.example.yaml",
) -> FastAPI:
    config = load_config(config_path)
    app = FastAPI(title="PromptAtelier Web Console", version="0.1.0")
    app.state.job_manager = job_manager or JobManager()
    app.state.config = config
    app.state.node_workspace = node_workspace or NodeWorkspace(design_root=config.legacy.design_root)
    app.state.result_index = result_index or ResultIndex(
        roots=[config.runtime.output_dir, "outputs", "examples/batches/outputs"],
    )
    app.state.generation_api = GenerationJsonApi(
        generation_executor=generation_executor or _default_generation_executor(config),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(jobs.router, prefix="/api", tags=["jobs"])
    app.include_router(nodes.router, prefix="/api", tags=["nodes"])
    app.include_router(compose.router, prefix="/api", tags=["compose"])
    app.include_router(generate.router, prefix="/api", tags=["generate"])
    app.include_router(results.router, prefix="/api", tags=["results"])
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
