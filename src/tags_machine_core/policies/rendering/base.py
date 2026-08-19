from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tags_machine_core.contracts import PromptBundle, RenderRequest
from tags_machine_core.nodes.resolved import ResolvedNodeSet
from tags_machine_core.policies.config import PolicyTarget, PromptPolicyConfig


@dataclass
class RenderPolicyContext:
    """Renderer Policy 的运行上下文，不进入 PromptBundle schema。"""

    request: RenderRequest
    bundle: PromptBundle
    resolved_nodes: ResolvedNodeSet | None
    policy: PromptPolicyConfig
    target: PolicyTarget
    design_root: Path | None = None
    policy_relative_to: Path | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)

    def add_trace(self, **entry: Any) -> None:
        self.trace.append({key: value for key, value in entry.items() if value is not None})


class RenderPolicy(Protocol):
    id: str
    version: str
    scope: str
    backend: str
    default_enabled: bool
    options_model: object

    def apply(self, context: RenderPolicyContext) -> RenderPolicyContext:
        ...
