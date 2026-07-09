from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .errors import ApiError, api_error_handler
from .routes import health, jobs
from .services.job_manager import JobManager


def create_app(*, job_manager: JobManager | None = None) -> FastAPI:
    app = FastAPI(title="PromptAtelier Web Console", version="0.1.0")
    app.state.job_manager = job_manager or JobManager()
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
    return app
