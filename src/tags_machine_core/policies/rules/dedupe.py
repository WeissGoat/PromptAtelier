from __future__ import annotations

from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.tokens import PromptToken


class DedupeRule:
    id = "dedupe"
    version = "v1"
    phase = "post_compose_cleanup"
    default_enabled = False

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        context.positive_tokens = self._dedupe(context.positive_tokens, context, "positive")
        context.negative_tokens = self._dedupe(context.negative_tokens, context, "negative")
        return context

    def _dedupe(
        self,
        tokens: list[PromptToken],
        context: PromptRuleContext,
        prompt_kind: str,
    ) -> list[PromptToken]:
        best_by_key: dict[str, PromptToken] = {}
        order: list[str] = []
        for token in tokens:
            key = token.canonical
            if key not in best_by_key:
                best_by_key[key] = token
                order.append(key)
                continue
            current = best_by_key[key]
            if token.weight_strength() > current.weight_strength():
                best_by_key[key] = token
            context.add_trace(
                rule=f"{self.id}@{self.version}",
                action="remove",
                token=token.render("underscore"),
                reason=f"duplicate {prompt_kind} token",
            )
        return [best_by_key[key] for key in order]
