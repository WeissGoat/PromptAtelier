from __future__ import annotations

from pathlib import Path
from typing import Iterable

from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.tokens import PromptToken, canonicalize_tag


DEFAULT_CONFLICTS: list[dict[str, list[str]]] = [
    {
        "when_any": [
            "barefoot",
            "barefeet",
            "bare_feet",
            "bare_foot",
            "bare_leg",
            "bare_legs",
            "bareleg",
            "barelegs",
        ],
        "remove": [
            "high_heel",
            "high_heels",
            "thighhigh",
            "thighhighs",
            "kneehighs",
            "socks",
            "sock",
            "pantyhose",
            "prosthesis",
            "boots",
            "legwear",
            "black_legwear",
        ],
        "keep": [
            "toeless_legwear",
            "mismatched_legwear",
            "asymmetrical_legwear",
        ],
    }
]


class TagConflictRule:
    id = "tag_conflict"
    version = "v1"
    phase = "post_compose_cleanup"
    default_enabled = False

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        rules = list(DEFAULT_CONFLICTS)
        options = context.config.options_for(self.id)
        masks_file = options.get("masks_file")
        if masks_file:
            rules.extend(_load_legacy_masks(Path(str(masks_file))))
        context.positive_tokens = self._apply_rules(context.positive_tokens, rules, context)
        return context

    def _apply_rules(
        self,
        tokens: list[PromptToken],
        rules: list[dict[str, list[str]]],
        context: PromptRuleContext,
    ) -> list[PromptToken]:
        active = {token.canonical for token in tokens}
        remove_keys: dict[str, str] = {}
        keep_keys: set[str] = set()
        for rule in rules:
            triggers = set(_canonical_list(rule.get("when_any", [])))
            if not triggers.intersection(active):
                continue
            for key in _canonical_list(rule.get("keep", [])):
                keep_keys.add(key)
            reason = "prompt tag conflict"
            for key in _canonical_list(rule.get("remove", [])):
                remove_keys[key] = reason

        result: list[PromptToken] = []
        for token in tokens:
            if token.canonical in keep_keys:
                result.append(token)
                continue
            matched_key = _matching_remove_key(token.canonical, remove_keys)
            if matched_key:
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="remove",
                    token=token.render("underscore"),
                    reason=f"{remove_keys[matched_key]}: {matched_key}",
                )
                continue
            result.append(token)
        return result


def _canonical_list(values: Iterable[str]) -> list[str]:
    return [canonicalize_tag(value) for value in values if canonicalize_tag(value)]


def _matching_remove_key(token_key: str, remove_keys: dict[str, str]) -> str | None:
    for key in remove_keys:
        if token_key == key or key in token_key:
            return key
    return None


def _load_legacy_masks(path: Path) -> list[dict[str, list[str]]]:
    if not path.exists():
        return []
    rules: list[dict[str, list[str]]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",") if part.strip()]
        if len(parts) < 2:
            continue
        keep: list[str] = []
        remove: list[str] = []
        for value in parts[1:]:
            if value.startswith("!"):
                keep.append(value[1:])
            else:
                remove.append(value)
        rules.append({"when_any": [parts[0]], "remove": remove, "keep": keep})
    return rules
