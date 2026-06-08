from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from tags_machine_core.contracts import PromptBundle
from tags_machine_core.nodes.resolved import ResolvedNodeSet
from tags_machine_core.policies.config import PromptPolicyConfig
from tags_machine_core.policies.tokens import PromptToken

RulePhase = Literal["normalize_input", "compose_selection", "post_compose_cleanup", "trace_finalize"]


@dataclass
class PromptPolicyTraceEntry:
    rule: str
    action: str
    token: str | None = None
    from_value: str | None = None
    to_value: str | None = None
    reason: str | None = None
    mode: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = {
            "rule": self.rule,
            "action": self.action,
            "token": self.token,
            "from": self.from_value,
            "to": self.to_value,
            "reason": self.reason,
            "mode": self.mode,
        }
        return {key: value for key, value in data.items() if value not in (None, "")}


@dataclass
class PromptRuleContext:
    bundle: PromptBundle
    resolved_nodes: ResolvedNodeSet | None
    config: PromptPolicyConfig
    positive_tokens: list[PromptToken]
    negative_tokens: list[PromptToken]
    target: str = "script"
    trace: list[PromptPolicyTraceEntry] = field(default_factory=list)

    def add_trace(
        self,
        *,
        rule: str,
        action: str,
        token: str | None = None,
        from_value: str | None = None,
        to_value: str | None = None,
        reason: str | None = None,
        mode: str | None = None,
    ) -> None:
        self.trace.append(
            PromptPolicyTraceEntry(
                rule=rule,
                action=action,
                token=token,
                from_value=from_value,
                to_value=to_value,
                reason=reason,
                mode=mode,
            )
        )


class PromptRule(Protocol):
    id: str
    version: str
    phase: RulePhase
    default_enabled: bool

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        ...
