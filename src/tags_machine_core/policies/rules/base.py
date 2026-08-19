from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from tags_machine_core.policies.context import PromptRuleContext


PolicyScope = Literal["prompt", "renderer"]

RulePhase = Literal[
    "normalize_input",
    "compose_selection",
    "post_compose_cleanup",
    "bundle_finalize",
]


class PromptRule(Protocol):
    id: str
    version: str
    phase: RulePhase
    default_enabled: bool
    options_model: object

    def apply(self, context: "PromptRuleContext") -> "PromptRuleContext":
        ...


def policy_scope(rule: object) -> str:
    """读取规则 scope，兼容现有未声明 scope 的 prompt 规则。"""
    return str(getattr(rule, "scope", "prompt"))


def policy_backend(rule: object) -> str | None:
    value = getattr(rule, "backend", None)
    return str(value) if value is not None else None
