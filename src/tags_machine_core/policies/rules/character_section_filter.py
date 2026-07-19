from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from pydantic import BaseModel, Field, field_validator

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.tokens import parse_prompt_tokens, render_prompt_tokens


class CharacterSectionFilterOptions(BaseModel):
    blocked_sections: list[str] = Field(default_factory=lambda: ["copyright"])

    @field_validator("blocked_sections", mode="before")
    @classmethod
    def normalize_blocked_sections(cls, value: Any) -> list[str]:
        if value is None:
            return ["copyright"]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        return [text] if text else []


class CharacterSectionFilterPolicyRule:
    id = "character_section_filter"
    version = "v1"
    phase = "compose_selection"
    default_enabled = False
    options_model = CharacterSectionFilterOptions

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        if context.target != "script" or context.resolved_nodes is None:
            return context

        options = CharacterSectionFilterOptions.model_validate(
            context.config.options_for(self.id)
        )
        blocked = set(options.blocked_sections)
        if not blocked:
            return context

        characters = context.resolved_nodes.characters()
        if not characters:
            return context

        extra = dict(context.bundle.meta.extra or {})
        existing_materials = extra.get("character_materials")
        materials_by_index = _materials_by_index(existing_materials)
        global_remove_counts: Counter[str] = Counter()
        token_sections: dict[str, set[str]] = defaultdict(set)
        updated_materials: list[dict[str, Any]] = []
        blocked_used_sections: list[str] = []

        for item in characters:
            material = dict(materials_by_index.get(item.index) or {})
            used_sections = _used_sections(
                material,
                context.bundle.meta.composition.included_character_sections,
                item.node,
            )
            active_blocked = [section for section in used_sections if section in blocked]
            blocked_used_sections.extend(active_blocked)

            remove_counts, section_by_token = _section_token_counts(
                item.node,
                active_blocked,
            )
            global_remove_counts.update(remove_counts)
            for token, sections in section_by_token.items():
                token_sections[token].update(sections)

            positive_tags = material.get("positive_tags")
            if not isinstance(positive_tags, list):
                positive_tags = _positive_values(item.node, used_sections)
            filtered_positive_tags = _filter_material_values(
                positive_tags,
                remove_counts.copy(),
            )

            suppressed_sections = _string_list(material.get("suppressed_sections"))
            if not material:
                available_sections = _available_sections(item.node)
                suppressed_sections = [
                    section for section in available_sections if section not in used_sections
                ]
            negative_tags = material.get("negative_tags")
            if not isinstance(negative_tags, list):
                scope = context.bundle.meta.composition.character_scope
                negative_tags = [
                    *item.node.negative_prompt,
                    *item.node.negative_texts(scope),
                ]
            updated_materials.append(
                {
                    **material,
                    "ref": material.get("ref") or item.ref,
                    "id": material.get("id") or item.node.id,
                    "index": item.index,
                    "used_sections": [
                        section for section in used_sections if section not in blocked
                    ],
                    "suppressed_sections": _dedupe(
                        [*suppressed_sections, *active_blocked]
                    ),
                    "positive_tags": filtered_positive_tags,
                    "negative_tags": negative_tags,
                    "blocked_sections": active_blocked,
                }
            )

        if not blocked_used_sections:
            return context

        context.positive_tokens = _filter_prompt_tokens(
            context,
            global_remove_counts,
            token_sections,
        )
        composition = context.bundle.meta.composition
        composition.included_character_sections = [
            section
            for section in composition.included_character_sections
            if section not in blocked
        ]
        composition.suppressed_character_sections = _dedupe(
            [
                *composition.suppressed_character_sections,
                *blocked_used_sections,
            ]
        )
        extra["character_materials"] = updated_materials
        context.bundle.meta.extra = extra
        return context


def _materials_by_index(value: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[int, dict[str, Any]] = {}
    for material in value:
        if not isinstance(material, dict):
            continue
        try:
            index = int(material.get("index", len(result)))
        except (TypeError, ValueError):
            index = len(result)
        result[index] = material
    return result


def _used_sections(
    material: dict[str, Any],
    included_sections: list[str],
    node: NodeDocument,
) -> list[str]:
    material_sections = _string_list(material.get("used_sections"))
    if material_sections:
        return material_sections
    if included_sections:
        return list(included_sections)
    if node.prompt.positive:
        return _dedupe([fragment.role or "prompt" for fragment in node.prompt.positive])
    return list(node.tags.keys())


def _section_token_counts(
    node: NodeDocument,
    sections: list[str],
) -> tuple[Counter[str], dict[str, set[str]]]:
    section_set = set(sections)
    counts: Counter[str] = Counter()
    token_sections: dict[str, set[str]] = defaultdict(set)
    if not section_set:
        return counts, token_sections

    if node.prompt.positive:
        sources = [
            (fragment.role or "prompt", fragment.text)
            for fragment in node.prompt.positive
            if (fragment.role or "prompt") in section_set
        ]
    else:
        sources = [
            (section, value)
            for section in sections
            for value in node.tags.get(section, [])
        ]

    for section, value in sources:
        for token in parse_prompt_tokens(value):
            if not token.canonical:
                continue
            counts[token.canonical] += 1
            token_sections[token.canonical].add(section)
    return counts, token_sections


def _positive_values(node: NodeDocument, used_sections: list[str]) -> list[str]:
    include = set(used_sections)
    if node.prompt.positive:
        return [
            fragment.text
            for fragment in node.prompt.positive
            if (fragment.role or "prompt") in include
        ]
    return [
        value
        for section in used_sections
        for value in node.tags.get(section, [])
    ]


def _available_sections(node: NodeDocument) -> list[str]:
    if node.prompt.positive:
        return _dedupe([fragment.role or "prompt" for fragment in node.prompt.positive])
    return list(node.tags.keys())


def _filter_material_values(values: list[Any], remove_counts: Counter[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        tokens = parse_prompt_tokens(str(value))
        if not tokens:
            continue
        kept = []
        for token in tokens:
            if remove_counts[token.canonical] > 0:
                remove_counts[token.canonical] -= 1
                continue
            kept.append(token)
        rendered = render_prompt_tokens(kept, "preserve")
        if rendered:
            result.append(rendered)
    return result


def _filter_prompt_tokens(
    context: PromptRuleContext,
    remove_counts: Counter[str],
    token_sections: dict[str, set[str]],
):
    result = []
    for token in context.positive_tokens:
        if remove_counts[token.canonical] <= 0:
            result.append(token)
            continue
        remove_counts[token.canonical] -= 1
        sections = sorted(token_sections.get(token.canonical) or [])
        context.add_trace(
            rule=f"{CharacterSectionFilterPolicyRule.id}@{CharacterSectionFilterPolicyRule.version}",
            action="remove",
            token=token.render("underscore"),
            reason="blocked character section: " + ", ".join(sections),
            mode="enforce",
        )
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
