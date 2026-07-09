from __future__ import annotations

from fastapi import APIRouter

from tags_machine_core.backends import backend_support_report


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "schema": "tags-machine-core.web.health/v1",
        "status": "ok",
    }


@router.get("/backend-support")
def backend_support() -> dict:
    return backend_support_report()
