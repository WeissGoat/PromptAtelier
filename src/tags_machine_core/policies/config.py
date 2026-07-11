from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PolicyTarget = Literal["script", "agent", "full_prompt"]
NormalizationOutputStyle = Literal["underscore", "preserve"]


class PromptPolicyApplyTo(BaseModel):
    script: bool = True
    agent: bool = False
    full_prompt: bool = False

    def enabled_for(self, target: PolicyTarget) -> bool:
        return bool(getattr(self, target))


class PromptNormalizationConfig(BaseModel):
    match_canonical: Literal["underscore"] = "underscore"
    output_style: NormalizationOutputStyle = "underscore"


class PromptPolicyRuleOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before: list[str] = Field(default_factory=list)
    after: list[str] = Field(default_factory=list)

    @field_validator("before", "after", mode="before")
    @classmethod
    def _normalize_rule_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []


class PromptPolicyRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    order: PromptPolicyRuleOrder = Field(default_factory=PromptPolicyRuleOrder)


class PromptPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    apply_to: PromptPolicyApplyTo = Field(default_factory=PromptPolicyApplyTo)
    normalization: PromptNormalizationConfig = Field(default_factory=PromptNormalizationConfig)
    enabled_rules: list[str] = Field(default_factory=list)
    disabled_rules: list[str] = Field(default_factory=list)
    rules: dict[str, PromptPolicyRuleConfig] = Field(default_factory=dict)
    template: str | None = None
    template_hash: str | None = None

    @field_validator("enabled_rules", "disabled_rules", mode="before")
    @classmethod
    def _normalize_rule_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []

    def target_enabled(self, target: PolicyTarget) -> bool:
        return self.enabled and self.apply_to.enabled_for(target)

    def rule_enabled(self, rule_id: str, default_enabled: bool = False) -> bool:
        if not self.enabled:
            return False
        rule_id = rule_id.strip()
        if rule_id in self.disabled_rules:
            return False
        rule_config = self.rules.get(rule_id)
        if rule_config is not None and rule_config.enabled is False:
            return False
        if rule_id in self.enabled_rules:
            return True
        if rule_config is not None and rule_config.enabled is True:
            return True
        return default_enabled

    def options_for(self, rule_id: str) -> dict[str, Any]:
        rule_config = self.rules.get(rule_id)
        return dict(rule_config.options) if rule_config is not None else {}

    def order_for(self, rule_id: str) -> PromptPolicyRuleOrder:
        rule_config = self.rules.get(rule_id)
        if rule_config is None:
            return PromptPolicyRuleOrder()
        return rule_config.order

    def cache_signature(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "apply_to": self.apply_to.model_dump(mode="json"),
            "normalization": self.normalization.model_dump(mode="json"),
            "enabled_rules": list(self.enabled_rules),
            "disabled_rules": list(self.disabled_rules),
            "rules": {
                rule_id: config.model_dump(mode="json")
                for rule_id, config in sorted(self.rules.items())
            },
        }
