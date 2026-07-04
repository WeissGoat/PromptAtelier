from __future__ import annotations

from tags_machine_core.policies.context import PromptRule, PromptRuleContext


class TagNormalizeRule:
    id = "tag_normalize"
    version = "v1"
    phase = "normalize_input"
    default_enabled = False

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        style = context.config.normalization.output_style
        if style != "underscore":
            return context
        for token in context.positive_tokens + context.negative_tokens:
            rendered = token.render("underscore")
            preserved = token.render("preserve")
            if rendered != preserved:
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="replace",
                    from_value=preserved,
                    to_value=rendered,
                    reason="canonical underscore normalization",
                )
        return context
