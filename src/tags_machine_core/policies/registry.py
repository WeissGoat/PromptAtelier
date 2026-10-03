from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import BaseModel

from tags_machine_core.policies.config import PromptPolicyConfig
from tags_machine_core.policies.ordering import resolve_rule_order
from tags_machine_core.policies.rules import DEFAULT_RULES, PromptRule
from tags_machine_core.policies.rules.base import policy_backend, policy_scope


@dataclass(frozen=True)
class PromptPolicyPlan:
    default_rules: list[PromptRule]
    effective_rules: list[PromptRule]


class PromptPolicyRegistry:
    def __init__(
        self,
        rules: Iterable[PromptRule] | None = None,
        renderer_rules: Iterable[object] | None = None,
    ):
        self.prompt_rules = list(rules or DEFAULT_RULES)
        if renderer_rules is None:
            try:
                from tags_machine_core.policies.rendering.novelai import DEFAULT_RENDER_RULES
            except ImportError:
                DEFAULT_RENDER_RULES = []
            renderer_rules = DEFAULT_RENDER_RULES
        self.renderer_rules = list(renderer_rules)
        self.rules = [*self.prompt_rules, *self.renderer_rules]
        self._by_id: dict[str, PromptRule] = {}
        for rule in self.rules:
            if rule.id in self._by_id:
                raise ValueError(f"Duplicate PromptPolicy rule id: {rule.id}")
            self._by_id[rule.id] = rule

    def validate_config(self, config: PromptPolicyConfig) -> PromptPolicyConfig:
        if (
            "novelai_vibe_artist" in config.rules
            or "novelai_vibe_artist" in config.enabled_rules
            or "novelai_vibe_artist" in config.disabled_rules
        ):
            config = config.model_copy(deep=True)
            if "novelai_vibe_artist" in config.rules:
                vibe_artist_rule = config.rules.pop("novelai_vibe_artist")
                if "novelai_vibe" not in config.rules:
                    opts = dict(vibe_artist_rule.options)
                    artist_ref = opts.pop("artist_ref", None)
                    if artist_ref and "source" not in opts:
                        opts["source"] = {"type": "artist", "ref": artist_ref}
                    if "source" in opts and isinstance(opts["source"], dict) and opts["source"].get("ref"):
                        vibe_artist_rule.options = opts
                        config.rules["novelai_vibe"] = vibe_artist_rule
            if "novelai_vibe_artist" in config.enabled_rules:
                config.enabled_rules = [
                    "novelai_vibe" if r == "novelai_vibe_artist" else r
                    for r in config.enabled_rules
                ]
            if "novelai_vibe_artist" in config.disabled_rules:
                config.disabled_rules = [
                    "novelai_vibe" if r == "novelai_vibe_artist" else r
                    for r in config.disabled_rules
                ]

        known_ids = set(self._by_id)
        configured_ids = set(config.rules) | set(config.enabled_rules) | set(config.disabled_rules)
        unknown = sorted(configured_ids - known_ids)
        if unknown:
            raise ValueError(f"Unknown PromptPolicy rules: {unknown}")

        order_refs = {
            target_id
            for rule_config in config.rules.values()
            for target_id in [*rule_config.order.before, *rule_config.order.after]
        }
        unknown_order_refs = sorted(order_refs - known_ids)
        if unknown_order_refs:
            raise ValueError(
                f"Unknown PromptPolicy rules in order constraints: {unknown_order_refs}"
            )

        updated = config.model_copy(deep=True)
        for rule_id, rule_config in updated.rules.items():
            rule = self._by_id[rule_id]
            options_model = getattr(rule, "options_model", None)
            if isinstance(options_model, type) and issubclass(options_model, BaseModel):
                validated = options_model.model_validate(rule_config.options)
                rule_config.options = validated.model_dump(mode="python")
        return updated

    def rules_for(self, *, scope: str = "prompt", backend: str | None = None) -> list[object]:
        return [
            rule
            for rule in self.rules
            if policy_scope(rule) == scope
            and (backend is None or policy_backend(rule) in (None, backend))
        ]

    def build_plan(
        self,
        config: PromptPolicyConfig,
        *,
        scope: str = "prompt",
        backend: str | None = None,
    ) -> PromptPolicyPlan:
        validated = self.validate_config(config)
        selected_rules = self.rules_for(scope=scope, backend=backend)
        enabled = [
            rule
            for rule in selected_rules
            if validated.rule_enabled(rule.id, default_enabled=rule.default_enabled)
        ]
        return PromptPolicyPlan(
            default_rules=enabled,
            effective_rules=resolve_rule_order(enabled, validated),
        )

    def rule(self, rule_id: str) -> object:
        try:
            return self._by_id[rule_id]
        except KeyError as exc:
            raise ValueError(f"Unknown PromptPolicy rule: {rule_id}") from exc
