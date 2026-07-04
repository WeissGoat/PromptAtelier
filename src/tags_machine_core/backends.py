from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tags_machine_core.contracts import BackendName


BACKEND_SUPPORT_SCHEMA = "tags-machine-core.backend-support/v1"
BackendStage = Literal["stable", "experimental"]


@dataclass(frozen=True)
class BackendSupport:
    backend: BackendName
    display_name: str
    stage: BackendStage
    render_plan_supported: bool
    execution_supported: bool
    executes_by_default: bool
    requires_experimental_execution: bool
    note: str

    def as_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "display_name": self.display_name,
            "stage": self.stage,
            "render_plan_supported": self.render_plan_supported,
            "execution_supported": self.execution_supported,
            "executes_by_default": self.executes_by_default,
            "requires_experimental_execution": self.requires_experimental_execution,
            "note": self.note,
        }


BACKEND_SUPPORT: dict[BackendName, BackendSupport] = {
    "novelai": BackendSupport(
        backend="novelai",
        display_name="NovelAI",
        stage="stable",
        render_plan_supported=True,
        execution_supported=True,
        executes_by_default=True,
        requires_experimental_execution=False,
        note="v1 正式接入和验收主线。",
    ),
    "comfyui": BackendSupport(
        backend="comfyui",
        display_name="ComfyUI",
        stage="stable",
        render_plan_supported=True,
        execution_supported=True,
        executes_by_default=True,
        requires_experimental_execution=False,
        note="正式 opt-in 后端；通过 artist node 的 API workflow 生成真实图片。",
    ),
    "sd": BackendSupport(
        backend="sd",
        display_name="Stable Diffusion WebUI / Forge",
        stage="experimental",
        render_plan_supported=True,
        execution_supported=True,
        executes_by_default=False,
        requires_experimental_execution=True,
        note="预研后端；SD/WebUI 正式规范确认前不进入 v1 验收。",
    ),
}

RENDER_BACKENDS = tuple(BACKEND_SUPPORT.keys())
DEFAULT_EXECUTION_BACKENDS = tuple(
    backend for backend, support in BACKEND_SUPPORT.items() if support.executes_by_default
)
EXPERIMENTAL_EXECUTION_BACKENDS = tuple(
    backend
    for backend, support in BACKEND_SUPPORT.items()
    if support.requires_experimental_execution
)


def get_backend_support(backend: str) -> BackendSupport:
    try:
        return BACKEND_SUPPORT[backend]  # type: ignore[index]
    except KeyError as exc:
        allowed = ", ".join(RENDER_BACKENDS)
        raise ValueError(f"Unsupported backend: {backend}; expected one of: {allowed}") from exc


def backend_support_report() -> dict[str, object]:
    return {
        "schema": BACKEND_SUPPORT_SCHEMA,
        "render_plan_backends": list(RENDER_BACKENDS),
        "default_execution_backends": list(DEFAULT_EXECUTION_BACKENDS),
        "experimental_execution_backends": list(EXPERIMENTAL_EXECUTION_BACKENDS),
        "items": [support.as_dict() for support in BACKEND_SUPPORT.values()],
    }


def ensure_backend_can_build_render_plan(
    backend: str,
    *,
    entrypoint: str = "render-plan",
) -> None:
    support = get_backend_support(backend)
    if not support.render_plan_supported:
        raise ValueError(f"{entrypoint} does not support render planning for backend: {backend}")


def ensure_backend_can_execute(
    backend: str,
    *,
    allow_experimental_backend: bool = False,
    entrypoint: str = "execute-render-request",
    experimental_flag: str | None = "--allow-experimental-backend",
) -> None:
    support = get_backend_support(backend)
    if not support.execution_supported:
        raise ValueError(f"{entrypoint} does not support backend execution for: {backend}")
    if support.executes_by_default:
        return
    if allow_experimental_backend and support.requires_experimental_execution:
        return

    stable_names = _display_names(DEFAULT_EXECUTION_BACKENDS)
    experimental_names = _display_names(EXPERIMENTAL_EXECUTION_BACKENDS)
    message = (
        f"{entrypoint} currently executes only {stable_names} by default; "
        f"{support.display_name} is a pre-v1 experimental backend."
    )
    if experimental_flag:
        message += f" Pass {experimental_flag} to run pre-v1 {experimental_names} clients."
    else:
        message += (
            " Use execute-render-request with --allow-experimental-backend "
            "for pre-v1 clients."
        )
    raise ValueError(message)


def _display_names(backends: tuple[BackendName, ...]) -> str:
    return ", ".join(BACKEND_SUPPORT[backend].display_name for backend in backends)
