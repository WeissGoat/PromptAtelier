from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tags_machine_core.logging_config import get_logger
from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.tokens import PromptToken, canonicalize_tag, parse_prompt_token


logger = get_logger(__name__)


InferencePosition = Literal["after_trigger", "append"]


class TagInferenceSpec(BaseModel):
    """一条基于已有 tag 推导新 tag 的规则。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    when_any: list[str]
    add: list[str]
    unless_any: list[str] = Field(default_factory=list)
    position: InferencePosition = "after_trigger"

    @field_validator("id", mode="before")
    @classmethod
    def _normalize_id(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("tag_inference rule id must not be empty")
        return text

    @field_validator("when_any", "add", "unless_any", mode="before")
    @classmethod
    def _normalize_tags(cls, value: Any, info) -> list[str]:
        if value is None:
            values: list[Any] = []
        elif isinstance(value, str):
            values = [value]
        elif isinstance(value, list):
            values = value
        else:
            raise ValueError(f"tag_inference {info.field_name} must be a list or string")

        result: list[str] = []
        for item in values:
            key = canonicalize_tag(str(item))
            if key and key not in result:
                result.append(key)
        if info.field_name in {"when_any", "add"} and not result:
            raise ValueError(f"tag_inference {info.field_name} must not be empty")
        return result


class TagInferenceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[TagInferenceSpec] = Field(default_factory=list)


class TagInferenceRule:
    id = "tag_inference"
    version = "v1"
    phase = "post_compose_cleanup"
    default_enabled = False
    options_model = TagInferenceOptions

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        options = TagInferenceOptions.model_validate(context.config.options_for(self.id))
        self._validate_rule_ids(options.rules)

        for spec in options.rules:
            self._apply_spec(context, spec)
        return context

    def _apply_spec(self, context: PromptRuleContext, spec: TagInferenceSpec) -> None:
        trigger_index = _first_matching_index(context.positive_tokens, spec.when_any)
        if trigger_index is None:
            return

        active = {token.canonical for token in context.positive_tokens}
        excluded = sorted(active.intersection(spec.unless_any))
        if excluded:
            context.add_trace(
                rule=f"{self.id}@{self.version}",
                action="skip",
                reason=f"{spec.id}: excluded by {', '.join(excluded)}",
                mode=spec.position,
            )
            return

        additions = [tag for tag in spec.add if tag not in active]
        if not additions:
            context.add_trace(
                rule=f"{self.id}@{self.version}",
                action="skip",
                token=", ".join(spec.add),
                reason=f"{spec.id}: target already exists",
                mode=spec.position,
            )
            return

        trigger = context.positive_tokens[trigger_index].render("underscore")
        new_tokens = list(context.positive_tokens)
        new_tokens_to_add = [parse_prompt_token(tag) for tag in additions]
        if spec.position == "after_trigger":
            new_tokens[trigger_index + 1 : trigger_index + 1] = new_tokens_to_add
        else:
            new_tokens.extend(new_tokens_to_add)
        context.positive_tokens = new_tokens

        for tag in additions:
            context.add_trace(
                rule=f"{self.id}@{self.version}",
                action="add",
                token=tag,
                reason=f"{spec.id}: inferred from {trigger}",
                mode=spec.position,
            )
        logger.info(
            "TagInferenceRule applied rule_id=%s trigger=%s added=%s position=%s",
            spec.id,
            trigger,
            additions,
            spec.position,
        )

    @staticmethod
    def _validate_rule_ids(rules: list[TagInferenceSpec]) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for spec in rules:
            if spec.id in seen:
                duplicates.add(spec.id)
            seen.add(spec.id)
        if duplicates:
            raise ValueError(
                "Duplicate tag_inference rule ids: "
                + ", ".join(sorted(duplicates))
            )


def _first_matching_index(tokens: list[PromptToken], values: list[str]) -> int | None:
    targets = set(values)
    for index, token in enumerate(tokens):
        if token.canonical in targets:
            return index
    return None
