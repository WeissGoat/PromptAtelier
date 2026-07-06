from __future__ import annotations

from collections import Counter

from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.tokens import PromptToken, canonicalize_tag


OUTFIT_SECTION_KEYS = {
    "clothes",
    "upper_clothes",
    "lower_clothes",
    "full_body_clothes",
    "outfit",
    "uniform",
    "dress",
    "shirt",
    "skirt",
    "jacket",
    "capelet",
    "legwear",
    "shoes",
}


class ClothingPolicyRule:
    id = "clothing_policy"
    version = "v2"
    phase = "compose_selection"
    default_enabled = False

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        options = context.config.options_for(self.id)
        mode = str(options.get("mode") or _default_mode(context))
        reasons = self._reasons_from_action_clothing(context)
        if not reasons:
            return context
        if mode == "advisory":
            for reason in reasons:
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="advise",
                    reason=reason,
                    mode=mode,
                )
            return context

        remove_counts = self._character_outfit_token_counts(context)
        if not remove_counts:
            context.add_trace(
                rule=f"{self.id}@{self.version}",
                action="skip",
                reason=";".join(reasons),
                mode=mode,
            )
            return context
        context.positive_tokens = self._filter_character_outfit_tokens(
            context.positive_tokens,
            context,
            reasons,
            remove_counts,
        )
        return context

    def _reasons_from_action_clothing(self, context: PromptRuleContext) -> list[str]:
        reasons: list[str] = []
        if context.resolved_nodes is None:
            return reasons
        for item in context.resolved_nodes.actions():
            clothing = item.node.clothing or {}
            if not isinstance(clothing, dict):
                continue
            state = str(clothing.get("state") or "").strip()
            action_outfit = bool(clothing.get("action_outfit"))
            if action_outfit:
                reasons.append(f"action_outfit:{item.node.id}")
            if state == "nude":
                reasons.append(f"state_nude:{item.node.id}")
        return reasons

    def _character_outfit_token_counts(self, context: PromptRuleContext) -> Counter[str]:
        counts: Counter[str] = Counter()
        if context.resolved_nodes is None:
            return counts
        included_sections = set(context.bundle.meta.composition.included_character_sections)
        for item in context.resolved_nodes.characters():
            if item.node.prompt.positive:
                for fragment in item.node.prompt.positive:
                    role = fragment.role or "prompt"
                    if role not in OUTFIT_SECTION_KEYS:
                        continue
                    if included_sections and role not in included_sections:
                        continue
                    canonical = canonicalize_tag(fragment.text)
                    if canonical:
                        counts[canonical] += 1
                continue
            for section, values in item.node.tags.items():
                if section not in OUTFIT_SECTION_KEYS:
                    continue
                if included_sections and section not in included_sections:
                    continue
                for value in values:
                    canonical = canonicalize_tag(value)
                    if canonical:
                        counts[canonical] += 1
        return counts

    def _filter_character_outfit_tokens(
        self,
        tokens: list[PromptToken],
        context: PromptRuleContext,
        reasons: list[str],
        remove_counts: Counter[str],
    ) -> list[PromptToken]:
        result: list[PromptToken] = []
        for token in tokens:
            if remove_counts[token.canonical] > 0:
                remove_counts[token.canonical] -= 1
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="remove",
                    token=token.render("underscore"),
                    reason=";".join(reasons),
                    mode="enforce",
                )
                continue
            result.append(token)
        return result


def _default_mode(context: PromptRuleContext) -> str:
    if context.target == "agent":
        return "advisory"
    return "enforce"
