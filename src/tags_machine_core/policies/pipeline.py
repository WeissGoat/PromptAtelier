from __future__ import annotations

import hashlib
import json

from tags_machine_core.contracts import CacheMeta, PromptBundle, PromptText
from tags_machine_core.logging_config import get_logger
from tags_machine_core.nodes.resolved import ResolvedNodeSet
from tags_machine_core.policies.config import PolicyTarget, PromptPolicyConfig
from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.registry import PromptPolicyPlan, PromptPolicyRegistry
from tags_machine_core.policies.rules import PromptRule
from tags_machine_core.policies.tokens import parse_prompt_tokens, render_prompt_tokens


logger = get_logger(__name__)


class PromptPolicyPipeline:
    def __init__(
        self,
        rules: list[PromptRule] | None = None,
        registry: PromptPolicyRegistry | None = None,
    ):
        self.registry = registry or PromptPolicyRegistry(rules)

    def apply(
        self,
        bundle: PromptBundle,
        *,
        resolved_nodes: ResolvedNodeSet | None = None,
        config: PromptPolicyConfig,
        target: PolicyTarget = "script",
    ) -> PromptBundle:
        policy = self.registry.validate_config(config)
        logger.trace(
            "PromptPolicyPipeline.apply called target=%s enabled=%s template=%s",
            target,
            policy.enabled,
            policy.template,
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
        plan = self.registry.build_plan(policy)
        enabled_rules = plan.effective_rules
        if not enabled_rules:
            logger.warning(
                "PromptPolicyPipeline enabled but no rules selected target=%s template=%s",
                target,
                policy.template,
            )
        else:
            logger.info(
                "PromptPolicyPipeline applying target=%s template=%s rules=%s",
                target,
                policy.template,
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
        self._write_policy_meta(working, policy, plan, context, target)
        self._update_cache_key(working, policy, enabled_rules)
        logger.info(
            "PromptPolicyPipeline complete target=%s trace_entries=%s positive_tokens=%s",
            target,
            len(context.trace),
            len(context.positive_tokens),
        )
        return working

    def _write_policy_meta(
        self,
        bundle: PromptBundle,
        policy: PromptPolicyConfig,
        plan: PromptPolicyPlan,
        context: PromptRuleContext,
        target: PolicyTarget,
    ) -> None:
        extra = dict(bundle.meta.extra or {})
        extra["policy"] = {
            "enabled": policy.enabled,
            "template": policy.template,
            "template_hash": policy.template_hash,
            "target": target,
            "normalization": policy.normalization.model_dump(mode="json"),
            "enabled_rules": [
                f"{rule.id}@{rule.version}" for rule in plan.effective_rules
            ],
            "default_rule_order": [
                f"{rule.id}@{rule.version}" for rule in plan.default_rules
            ],
            "effective_rule_order": [
                f"{rule.id}@{rule.version}" for rule in plan.effective_rules
            ],
            "order_overrides": {
                rule_id: config.order.model_dump(mode="json")
                for rule_id, config in policy.rules.items()
                if config.order.before or config.order.after
            },
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
