from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Iterable

from tags_machine_core.logging_config import get_logger
from tags_machine_core.policies.config import PromptPolicyConfig
from tags_machine_core.policies.rules.base import PromptRule


logger = get_logger(__name__)


PHASE_ORDER = {
    "normalize_input": 0,
    "compose_selection": 1,
    "post_compose_cleanup": 2,
    "bundle_finalize": 3,
}


def resolve_rule_order(
    rules: Iterable[PromptRule],
    config: PromptPolicyConfig,
) -> list[PromptRule]:
    default_rules = list(rules)
    by_id = {rule.id: rule for rule in default_rules}
    default_index = {rule.id: index for index, rule in enumerate(default_rules)}
    edges: dict[str, set[str]] = defaultdict(set)
    indegree = {rule.id: 0 for rule in default_rules}

    for rule in default_rules:
        order = config.order_for(rule.id)
        for target_id in order.before:
            _add_constraint(
                source_id=rule.id,
                target_id=target_id,
                by_id=by_id,
                edges=edges,
                indegree=indegree,
            )
        for source_id in order.after:
            _add_constraint(
                source_id=source_id,
                target_id=rule.id,
                by_id=by_id,
                edges=edges,
                indegree=indegree,
            )

    ready: list[tuple[int, str]] = [
        (default_index[rule_id], rule_id)
        for rule_id, degree in indegree.items()
        if degree == 0
    ]
    heapq.heapify(ready)
    result: list[PromptRule] = []
    while ready:
        _, rule_id = heapq.heappop(ready)
        result.append(by_id[rule_id])
        for target_id in sorted(edges.get(rule_id, ()), key=default_index.__getitem__):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                heapq.heappush(ready, (default_index[target_id], target_id))

    if len(result) != len(default_rules):
        cycle = sorted(rule_id for rule_id, degree in indegree.items() if degree > 0)
        raise ValueError(f"PromptPolicy rule order contains a cycle: {cycle}")

    return sorted(result, key=lambda rule: (PHASE_ORDER[rule.phase], result.index(rule)))


def _add_constraint(
    *,
    source_id: str,
    target_id: str,
    by_id: dict[str, PromptRule],
    edges: dict[str, set[str]],
    indegree: dict[str, int],
) -> None:
    if source_id == target_id:
        raise ValueError(f"PromptPolicy rule cannot order itself: {source_id}")
    if source_id not in by_id or target_id not in by_id:
        logger.warning(
            "PromptPolicy order constraint ignored because rule is disabled source=%s target=%s",
            source_id,
            target_id,
        )
        return

    source_phase = PHASE_ORDER[by_id[source_id].phase]
    target_phase = PHASE_ORDER[by_id[target_id].phase]
    if source_phase > target_phase:
        raise ValueError(
            "PromptPolicy order constraint violates fixed phase order: "
            f"{source_id} before {target_id}"
        )
    if source_phase < target_phase:
        return
    if target_id in edges[source_id]:
        return
    edges[source_id].add(target_id)
    indegree[target_id] += 1
