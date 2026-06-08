from __future__ import annotations

from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.tokens import PromptToken, parse_prompt_token


NUDE_KEYS = {"nude", "naked", "completely_nude"}
CLOTHING_CONTROL_KEYS = {
    "st_clothes",
    "st_clothes_2",
    "st_clothes_3",
    "clothing_control",
    "changing_clothes",
}
OUTFIT_KEYS = {
    "clothes",
    "outfit",
    "uniform",
    "dress",
    "shirt",
    "skirt",
    "jacket",
    "capelet",
    "upper_clothes",
    "full_body_clothes",
}
FOOT_DETAIL_SCOPES = {"foot_detail", "lower_body"}


class ClothingPolicyRule:
    id = "clothing_policy"
    version = "v1"
    phase = "compose_selection"
    default_enabled = False

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        options = context.config.options_for(self.id)
        mode = str(options.get("mode") or _default_mode(context))
        reasons = self._reasons(context)
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

        context.positive_tokens = self._filter_outfit_tokens(context.positive_tokens, context, reasons)
        if "clothing_control" in reasons and not _has_token(context.positive_tokens, "alternative_clothing"):
            context.positive_tokens.append(parse_prompt_token("{{alternative_clothing}}"))
            context.add_trace(
                rule=f"{self.id}@{self.version}",
                action="add",
                token="{{alternative_clothing}}",
                reason="clothing_control",
                mode=mode,
            )
        return context

    def _reasons(self, context: PromptRuleContext) -> list[str]:
        token_keys = {token.canonical for token in context.positive_tokens}
        reasons: list[str] = []
        if any(key in token_keys for key in NUDE_KEYS):
            reasons.append("nude_prompt")
        if any(key in token_keys for key in CLOTHING_CONTROL_KEYS):
            reasons.append("clothing_control")
        scope = context.bundle.meta.composition.character_scope
        if scope in FOOT_DETAIL_SCOPES:
            reasons.append(f"scope_{scope}")
        return reasons

    def _filter_outfit_tokens(
        self,
        tokens: list[PromptToken],
        context: PromptRuleContext,
        reasons: list[str],
    ) -> list[PromptToken]:
        result: list[PromptToken] = []
        for token in tokens:
            if _is_outfit_token(token):
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


def _is_outfit_token(token: PromptToken) -> bool:
    key = token.canonical
    return any(part in key for part in OUTFIT_KEYS)


def _has_token(tokens: list[PromptToken], canonical: str) -> bool:
    return any(token.canonical == canonical for token in tokens)
