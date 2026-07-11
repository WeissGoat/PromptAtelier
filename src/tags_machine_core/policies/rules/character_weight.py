from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.tokens import PromptToken, canonicalize_tag, parse_prompt_tokens


class CharacterWeightOptions(BaseModel):
    style: Literal["braces", "numeric"] = "numeric"
    level: int = Field(default=2, ge=1, le=6)
    numeric_weight: float = Field(default=2.0, gt=0, le=10)
    existing_weight: Literal["replace", "keep", "increase"] = "replace"
    missing_identity: Literal["ignore", "error"] = "ignore"
    identities: list[str] = Field(default_factory=list)


class CharacterWeightPolicyRule:
    id = "character_weight"
    version = "v1"
    phase = "bundle_finalize"
    default_enabled = False
    options_model = CharacterWeightOptions

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        options = CharacterWeightOptions.model_validate(context.config.options_for(self.id))
        identities = self._identity_keys(context, options)
        if not identities:
            if options.missing_identity == "error":
                raise ValueError("character_weight found no character identity tokens")
            return context

        matched: set[str] = set()
        result: list[PromptToken] = []
        for token in context.positive_tokens:
            if token.canonical not in identities:
                result.append(token)
                continue
            matched.add(token.canonical)
            weighted = _apply_weight(token, options)
            result.append(weighted)
            before = token.render("underscore")
            after = weighted.render("underscore")
            if before != after:
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="replace_weight",
                    token=token.canonical,
                    from_value=before,
                    to_value=after,
                    reason=f"matched character identity: {token.canonical}",
                    mode=options.existing_weight,
                )

        missing = identities - matched
        if missing and options.missing_identity == "error":
            raise ValueError(
                "character_weight identities are missing from positive prompt: "
                f"{sorted(missing)}"
            )
        context.positive_tokens = result
        return context

    def _identity_keys(
        self,
        context: PromptRuleContext,
        options: CharacterWeightOptions,
    ) -> set[str]:
        values = list(options.identities)
        if context.resolved_nodes is not None:
            for item in context.resolved_nodes.characters():
                node_values: list[str] = []
                for fragment in item.node.prompt.positive:
                    if (fragment.role or "") == "character":
                        node_values.append(fragment.text)
                node_values.extend(item.node.tags.get("character", []))
                if item.node.character_id:
                    node_values.append(item.node.character_id)
                values.extend(node_values)

        keys: set[str] = set()
        for value in values:
            parsed = parse_prompt_tokens(value)
            if parsed:
                keys.update(token.canonical for token in parsed if token.canonical)
                continue
            canonical = canonicalize_tag(value)
            if canonical:
                keys.add(canonical)
        return keys


def _apply_weight(token: PromptToken, options: CharacterWeightOptions) -> PromptToken:
    if options.existing_weight == "keep" and (token.weight_prefix or token.weight_suffix):
        return token

    if options.style == "numeric":
        numeric_weight = options.numeric_weight
        if options.existing_weight == "increase" and token.weight_prefix.endswith("::"):
            try:
                numeric_weight += float(token.weight_prefix.removesuffix("::")) - 1.0
            except ValueError:
                pass
        prefix = f"{_format_numeric_weight(numeric_weight)}::"
        suffix = "::"
    else:
        level = options.level
        if options.existing_weight == "increase" and token.weight_prefix.startswith("{"):
            level += len(token.weight_prefix)
        prefix = "{" * level
        suffix = "}" * level

    return PromptToken(
        raw=token.raw,
        body=token.body,
        canonical=token.canonical,
        weight_prefix=prefix,
        weight_suffix=suffix,
        separator=token.separator,
    )


def _format_numeric_weight(value: float) -> str:
    if float(value).is_integer():
        return f"{value:.1f}"
    return f"{value:g}"
