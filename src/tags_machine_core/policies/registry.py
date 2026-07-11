from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import BaseModel

from tags_machine_core.policies.config import PromptPolicyConfig
from tags_machine_core.policies.ordering import resolve_rule_order
from tags_machine_core.policies.rules import DEFAULT_RULES, PromptRule


@dataclass(frozen=True)
class PromptPolicyPlan:
    default_rules: list[PromptRule]
    effective_rules: list[PromptRule]


class PromptPolicyRegistry:
    def __init__(self, rules: Iterable[PromptRule] | None = None):
        self.rules = list(rules or DEFAULT_RULES)
        self._by_id: dict[str, PromptRule] = {}
        for rule in self.rules:
            if rule.id in self._by_id:
                raise ValueError(f"Duplicate PromptPolicy rule id: {rule.id}")
            self._by_id[rule.id] = rule

    def validate_config(self, config: PromptPolicyConfig) -> PromptPolicyConfig:
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

    def build_plan(self, config: PromptPolicyConfig) -> PromptPolicyPlan:
        validated = self.validate_config(config)
        enabled = [
            rule
            for rule in self.rules
            if validated.rule_enabled(rule.id, default_enabled=rule.default_enabled)
        ]
        return PromptPolicyPlan(
            default_rules=enabled,
            effective_rules=resolve_rule_order(enabled, validated),
        )

    def rule(self, rule_id: str) -> PromptRule:
        try:
            return self._by_id[rule_id]
        except KeyError as exc:
            raise ValueError(f"Unknown PromptPolicy rule: {rule_id}") from exc
