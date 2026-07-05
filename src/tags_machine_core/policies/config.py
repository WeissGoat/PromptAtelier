from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


PolicyTarget = Literal["script", "agent", "full_prompt"]
NormalizationOutputStyle = Literal["underscore", "preserve"]


PROFILE_RULES: dict[str, list[str]] = {
    "off": [],
    "normalize_only": ["tag_normalize", "dedupe"],
    "balanced": [
        "tag_normalize",
        "dedupe",
        "tag_conflict",
        "character_count",
        "clothing_policy",
        "visibility_policy",
    ],
    "strict": [
        "tag_normalize",
        "dedupe",
        "tag_conflict",
        "character_count",
        "clothing_policy",
        "visibility_policy",
    ],
    "legacy_compat": [
        "tag_normalize",
        "dedupe",
        "character_extension",
        "tag_conflict",
        "character_count",
        "clothing_policy",
        "visibility_policy",
    ],
}


class PromptPolicyApplyTo(BaseModel):
    script: bool = True
    agent: bool = False
    full_prompt: bool = False

    def enabled_for(self, target: PolicyTarget) -> bool:
        return bool(getattr(self, target))


class PromptNormalizationConfig(BaseModel):
    match_canonical: Literal["underscore"] = "underscore"
    output_style: NormalizationOutputStyle = "underscore"


class PromptPolicyConfig(BaseModel):
    enabled: bool = False
    profile: str = "off"
    apply_to: PromptPolicyApplyTo = Field(default_factory=PromptPolicyApplyTo)
    normalization: PromptNormalizationConfig = Field(default_factory=PromptNormalizationConfig)
    enabled_rules: list[str] = Field(default_factory=list)
    disabled_rules: list[str] = Field(default_factory=list)
    rules: dict[str, dict[str, Any]] = Field(default_factory=dict)
    rule_options: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator("enabled_rules", "disabled_rules", mode="before")
    @classmethod
    def _normalize_rule_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_rule_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        raw_rules = data.get("rules")
        normalized_rules: dict[str, dict[str, Any]] = {}
        if isinstance(raw_rules, dict):
            for rule_id, rule_value in raw_rules.items():
                key = str(rule_id).strip()
                if not key:
                    continue
                if isinstance(rule_value, bool):
                    normalized_rules[key] = {"enabled": rule_value}
                elif isinstance(rule_value, dict):
                    normalized_rules[key] = dict(rule_value)
                else:
                    normalized_rules[key] = {"enabled": bool(rule_value)}
        if normalized_rules:
            data["rules"] = normalized_rules
        return data

    def target_enabled(self, target: PolicyTarget) -> bool:
        return self.enabled and self.apply_to.enabled_for(target)

    def rule_enabled(self, rule_id: str, default_enabled: bool = False) -> bool:
        if not self.enabled:
            return False
        rule_id = rule_id.strip()
        if rule_id in self.disabled_rules:
            return False
        rule_config = self.rules.get(rule_id) or {}
        if rule_config.get("enabled") is False:
            return False
        if rule_id in self.enabled_rules:
            return True
        if rule_config.get("enabled") is True:
            return True
        profile_rules = PROFILE_RULES.get(self.profile, PROFILE_RULES["off"])
        if rule_id in profile_rules:
            return True
        return default_enabled

    def options_for(self, rule_id: str) -> dict[str, Any]:
        options: dict[str, Any] = {}
        options.update(self.rule_options.get(rule_id) or {})
        options.update(self.rules.get(rule_id) or {})
        options.pop("enabled", None)
        return options

    def cache_signature(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "profile": self.profile,
            "apply_to": self.apply_to.model_dump(mode="json"),
            "normalization": self.normalization.model_dump(mode="json"),
            "enabled_rules": list(self.enabled_rules),
            "disabled_rules": list(self.disabled_rules),
            "rules": self.rules,
            "rule_options": self.rule_options,
        }
