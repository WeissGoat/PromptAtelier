from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from tags_machine_core.policies.context import PromptRuleContext


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
