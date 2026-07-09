from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tags_machine_core.config import load_config

from .errors import ApiError, api_error_handler
from .routes import health, jobs, nodes
from .services.job_manager import JobManager
from .services.node_workspace import NodeWorkspace


def create_app(
    *,
    job_manager: JobManager | None = None,
    node_workspace: NodeWorkspace | None = None,
) -> FastAPI:
    app = FastAPI(title="PromptAtelier Web Console", version="0.1.0")
    app.state.job_manager = job_manager or JobManager()
    app.state.node_workspace = node_workspace or _default_node_workspace()
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
    return app


def _default_node_workspace() -> NodeWorkspace:
    config_path = Path("configs/local.example.yaml")
    config = load_config(config_path)
    return NodeWorkspace(design_root=config.legacy.design_root)
