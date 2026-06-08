from __future__ import annotations

from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.tokens import PromptToken


FACE_HIDDEN_TRIGGERS = {
    "from_back",
    "facing_away",
    "head_down",
    "closed_eye",
    "close_eye",
    "eye_mask",
    "sleep",
    "blindfold",
}
HEAD_OUT_TRIGGERS = {"head_out_of_frame"}
FOOT_FOCUS_TRIGGERS = {"foot_focus", "sole_focus", "soles_focus", "lower_body"}
EYE_KEYS = {"eyes", "pupils", "eye_color", "@_@", "+_+"}
FACE_KEYS = {"face", "mouth", "nose", "expression"}
HAIR_KEYS = {"hair", "hair_detail"}
UPPER_CLOTHES_KEYS = {"upper_clothes", "shirt", "jacket", "capelet", "uniform"}


class VisibilityPolicyRule:
    id = "visibility_policy"
    version = "v1"
    phase = "compose_selection"
    default_enabled = False

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        options = context.config.options_for(self.id)
        mode = str(options.get("mode") or _default_mode(context))
        suppressed = self._suppressed_keys(context)
        if not suppressed:
            return context
        if mode == "advisory":
            context.add_trace(
                rule=f"{self.id}@{self.version}",
                action="advise",
                token=", ".join(sorted(suppressed)),
                reason="visibility scope suggests suppressing character detail",
                mode=mode,
            )
            return context
        context.positive_tokens = self._filter_tokens(context.positive_tokens, suppressed, context)
        return context

    def _suppressed_keys(self, context: PromptRuleContext) -> set[str]:
        token_keys = {token.canonical for token in context.positive_tokens}
        suppressed: set[str] = set()
        if token_keys.intersection(FACE_HIDDEN_TRIGGERS):
            suppressed.update(EYE_KEYS)
        if token_keys.intersection(HEAD_OUT_TRIGGERS):
            suppressed.update(EYE_KEYS)
            suppressed.update(FACE_KEYS)
            suppressed.update(HAIR_KEYS)
        if token_keys.intersection(FOOT_FOCUS_TRIGGERS):
            suppressed.update(EYE_KEYS)
            suppressed.update(FACE_KEYS)
            suppressed.update(HAIR_KEYS)
            suppressed.update(UPPER_CLOTHES_KEYS)
        scope = context.bundle.meta.composition.character_scope
        if scope in {"foot_detail", "lower_body"}:
            suppressed.update(EYE_KEYS)
            suppressed.update(FACE_KEYS)
            suppressed.update(HAIR_KEYS)
            suppressed.update(UPPER_CLOTHES_KEYS)
        return suppressed

    def _filter_tokens(
        self,
        tokens: list[PromptToken],
        suppressed: set[str],
        context: PromptRuleContext,
    ) -> list[PromptToken]:
        result: list[PromptToken] = []
        for token in tokens:
            matched = _matched_key(token, suppressed)
            if matched:
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="remove",
                    token=token.render("underscore"),
                    reason=f"not visible in current shot: {matched}",
                    mode="enforce",
                )
                continue
            result.append(token)
        return result


def _default_mode(context: PromptRuleContext) -> str:
    if context.target == "agent":
        return "advisory"
    return "enforce"


def _matched_key(token: PromptToken, keys: set[str]) -> str | None:
    for key in keys:
        if token.canonical == key or key in token.canonical:
            return key
    return None
