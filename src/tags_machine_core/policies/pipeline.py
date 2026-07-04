from __future__ import annotations

import hashlib
import json
from typing import Iterable

from tags_machine_core.contracts import CacheMeta, PromptBundle, PromptText
from tags_machine_core.logging_config import get_logger
from tags_machine_core.nodes.resolved import ResolvedNodeSet
from tags_machine_core.policies.config import PolicyTarget, PromptPolicyConfig
from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.rules import DEFAULT_RULES, PromptRule
from tags_machine_core.policies.tokens import parse_prompt_tokens, render_prompt_tokens


PHASE_ORDER = {
    "normalize_input": 0,
    "compose_selection": 1,
    "post_compose_cleanup": 2,
    "bundle_finalize": 3,
}


logger = get_logger(__name__)


class PromptPolicyPipeline:
    def __init__(self, rules: Iterable[PromptRule] | None = None):
        self.rules = list(rules or DEFAULT_RULES)

    def apply(
        self,
        bundle: PromptBundle,
        *,
        resolved_nodes: ResolvedNodeSet | None = None,
        config: PromptPolicyConfig | dict | None = None,
        target: PolicyTarget = "script",
    ) -> PromptBundle:
        policy = _coerce_config(config)
        logger.trace(
            "PromptPolicyPipeline.apply called target=%s enabled=%s profile=%s",
            target,
            policy.enabled,
            policy.profile,
        )
        if not policy.target_enabled(target):
            logger.trace(
                "PromptPolicyPipeline skipped target=%s enabled=%s apply_to=%s",
                target,
                policy.enabled,
                policy.apply_to.model_dump(mode="json"),
            )
            return bundle

        working = bundle.model_copy(deep=True)
        context = PromptRuleContext(
            bundle=working,
            resolved_nodes=resolved_nodes,
            target=target,
            config=policy,
            positive_tokens=parse_prompt_tokens(working.prompt.positive),
            negative_tokens=parse_prompt_tokens(working.prompt.negative),
        )
        enabled_rules = self._enabled_rules(policy)
        if not enabled_rules:
            logger.warning(
                "PromptPolicyPipeline enabled but no rules selected target=%s profile=%s",
                target,
                policy.profile,
            )
        else:
            logger.info(
                "PromptPolicyPipeline applying target=%s profile=%s rules=%s",
                target,
                policy.profile,
                [rule.id for rule in enabled_rules],
            )
        for rule in enabled_rules:
            before_trace_count = len(context.trace)
            context = rule.apply(context)
            logger.trace(
                "PromptPolicyPipeline rule applied rule=%s new_trace_entries=%s",
                rule.id,
                len(context.trace) - before_trace_count,
            )

        output_style = policy.normalization.output_style
        positive = render_prompt_tokens(context.positive_tokens, output_style)
        negative = render_prompt_tokens(context.negative_tokens, output_style)
        working.prompt = PromptText(positive=positive, negative=negative)
        self._write_policy_meta(working, policy, enabled_rules, context, target)
        self._update_cache_key(working, policy, enabled_rules)
        logger.info(
            "PromptPolicyPipeline complete target=%s trace_entries=%s positive_tokens=%s",
            target,
            len(context.trace),
            len(context.positive_tokens),
        )
        return working

    def _enabled_rules(self, policy: PromptPolicyConfig) -> list[PromptRule]:
        rules = [
            rule
            for rule in self.rules
            if policy.rule_enabled(rule.id, default_enabled=rule.default_enabled)
        ]
        return sorted(rules, key=lambda rule: PHASE_ORDER.get(rule.phase, 99))

    def _write_policy_meta(
        self,
        bundle: PromptBundle,
        policy: PromptPolicyConfig,
        rules: list[PromptRule],
        context: PromptRuleContext,
        target: PolicyTarget,
    ) -> None:
        extra = dict(bundle.meta.extra or {})
        extra["policy"] = {
            "enabled": policy.enabled,
            "profile": policy.profile,
            "target": target,
            "normalization": policy.normalization.model_dump(mode="json"),
            "enabled_rules": [f"{rule.id}@{rule.version}" for rule in rules],
            "disabled_rules": list(policy.disabled_rules),
        }
        extra["policy_trace"] = [
            entry.as_dict()
            for entry in context.trace
        ]
        bundle.meta.extra = extra

    def _update_cache_key(
        self,
        bundle: PromptBundle,
        policy: PromptPolicyConfig,
        rules: list[PromptRule],
    ) -> None:
        base_key = bundle.cache.cache_key or ""
        payload = {
            "base_key": base_key,
            "policy": policy.cache_signature(),
            "rules": [f"{rule.id}@{rule.version}" for rule in rules],
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        bundle.cache = CacheMeta(
            cacheable=bundle.cache.cacheable,
            cache_key="sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
            cache_hit=bundle.cache.cache_hit,
        )


def _coerce_config(config: PromptPolicyConfig | dict | None) -> PromptPolicyConfig:
    if isinstance(config, PromptPolicyConfig):
        return config
    if isinstance(config, dict):
        return PromptPolicyConfig.model_validate(config)
    return PromptPolicyConfig()
