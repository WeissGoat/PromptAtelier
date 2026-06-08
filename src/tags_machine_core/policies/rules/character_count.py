from __future__ import annotations

import re

from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.tokens import parse_prompt_token


_COUNT_RE = re.compile(
    r"^(?:\d+|multiple)_(?:girl|girls|boy|boys|woman|women|man|men)$"
)


class CharacterCountRule:
    id = "character_count"
    version = "v1"
    phase = "post_compose_cleanup"
    default_enabled = False

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        count_tokens = [token for token in context.positive_tokens if _is_count_token(token.canonical)]
        if count_tokens:
            rest = [token for token in context.positive_tokens if not _is_count_token(token.canonical)]
            if context.positive_tokens[: len(count_tokens)] != count_tokens:
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="move",
                    token=", ".join(token.render("underscore") for token in count_tokens),
                    reason="character count tags should be prompt-leading",
                )
            context.positive_tokens = count_tokens + rest
            return context

        character_count = self._resolved_character_count(context)
        if character_count <= 0 or not context.positive_tokens:
            return context
        tag = "1girl" if character_count == 1 else f"{character_count}girls"
        context.positive_tokens.insert(0, parse_prompt_token(tag))
        context.add_trace(
            rule=f"{self.id}@{self.version}",
            action="add",
            token=tag,
            reason="no explicit character count tag",
        )
        return context

    def _resolved_character_count(self, context: PromptRuleContext) -> int:
        if context.resolved_nodes is not None:
            count = len(context.resolved_nodes.characters())
            if count:
                return count
        node_refs = context.bundle.meta.nodes
        count = len([node for node in node_refs if node.role == "character"])
        if count:
            return count
        return 1


def _is_count_token(value: str) -> bool:
    return bool(_COUNT_RE.match(value))
