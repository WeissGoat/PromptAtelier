from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PromptPolicyRuleOrderSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before: list[str] | None = None
    after: list[str] | None = None


class PromptPolicyRuleSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    options: dict[str, Any] | None = None
    order: PromptPolicyRuleOrderSource | None = None


class PromptPolicySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require: str | None = None
    enabled: bool | None = None
    apply_to: dict[str, bool] | None = None
    normalization: dict[str, Any] | None = None
    enabled_rules: list[str] | None = None
    disabled_rules: list[str] | None = None
    rules: dict[str, PromptPolicyRuleSource] | None = None

    @model_validator(mode="before")
    @classmethod
    def _translate_legacy_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        profile = data.pop("profile", None)
        if profile and "require" not in data:
            data["require"] = str(profile)

        raw_rules = data.get("rules")
        if isinstance(raw_rules, dict):
            normalized: dict[str, Any] = {}
            for rule_id, rule_value in raw_rules.items():
                if isinstance(rule_value, bool):
                    normalized[str(rule_id)] = {"enabled": rule_value}
                    continue
                if not isinstance(rule_value, dict):
                    normalized[str(rule_id)] = {"enabled": bool(rule_value)}
                    continue
                item = dict(rule_value)
                if "options" not in item:
                    options = {
                        key: option
                        for key, option in item.items()
                        if key not in {"enabled", "order"}
                    }
                    item = {
                        key: option
                        for key, option in item.items()
                        if key in {"enabled", "order"}
                    }
                    if options:
                        item["options"] = options
                normalized[str(rule_id)] = item
            data["rules"] = normalized

        legacy_options = data.pop("rule_options", None)
        if isinstance(legacy_options, dict):
            rules = dict(data.get("rules") or {})
            for rule_id, options in legacy_options.items():
                item = dict(rules.get(str(rule_id)) or {})
                merged_options = dict(options) if isinstance(options, dict) else {}
                merged_options.update(item.get("options") or {})
                item["options"] = merged_options
                rules[str(rule_id)] = item
            data["rules"] = rules
        return data

    def as_mapping(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True, mode="python")
