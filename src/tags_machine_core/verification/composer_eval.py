from __future__ import annotations

from typing import Any

from tags_machine_core.contracts import PromptBundle


LOCAL_DETAIL_SCOPES = {"foot_detail", "hand_detail"}


def build_composer_evaluation_report(
    *,
    case_id: str,
    prompt_bundle: PromptBundle,
    legacy_prompt: str | None = None,
) -> dict[str, Any]:
    composition = prompt_bundle.meta.composition
    suppressed = composition.suppressed_character_sections
    intentional_differences: list[dict[str, Any]] = []
    if composition.character_scope in LOCAL_DETAIL_SCOPES and suppressed:
        intentional_differences.append(
            {
                "scope": composition.character_scope,
                "reason": "局部镜头按统一 composer policy 过滤无关角色 section",
                "suppressed_character_sections": suppressed,
            }
        )

    return {
        "schema": "tags-machine-core.composer-evaluation/v1",
        "case_id": case_id,
        "prompt": prompt_bundle.prompt.model_dump(mode="json"),
        "composition": composition.model_dump(mode="json"),
        "legacy": {"prompt": legacy_prompt or ""},
        "intentional_differences": intentional_differences,
        "visual": {
            "result": "pending",
            "notes": "",
            "checked_at": None,
        },
    }
