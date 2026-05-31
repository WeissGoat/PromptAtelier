from __future__ import annotations

from typing import Any

from tags_machine_core.nodes.models import NodeDocument


CHARACTER_SCOPE_POLICY: dict[str, dict[str, list[str] | None]] = {
    "default": {"include": None},
    "full_body": {"include": None},
    "upper_body": {
        "include": [
            "character",
            "identity",
            "copyright",
            "role",
            "hair",
            "eyes",
            "face",
            "head_accessories",
            "ears",
            "upper_clothes",
            "full_body_clothes",
            "handwear",
            "body",
            "hands",
            "accessories",
            "weapons",
            "props",
            "wings",
            "tail",
            "extra",
        ],
    },
    "lower_body": {
        "include": [
            "character",
            "identity",
            "copyright",
            "role",
            "body",
            "lower_clothes",
            "full_body_clothes",
            "legwear",
            "footwear",
            "feet",
            "tail",
            "extra",
        ],
    },
    "portrait": {
        "include": [
            "character",
            "identity",
            "copyright",
            "role",
            "hair",
            "eyes",
            "face",
            "head_accessories",
            "ears",
            "upper_clothes",
            "accessories",
            "extra",
        ],
    },
    "face_detail": {
        "include": [
            "character",
            "identity",
            "copyright",
            "role",
            "hair",
            "eyes",
            "face",
            "head_accessories",
            "ears",
            "extra",
        ],
    },
    "hand_detail": {
        "include": [
            "character",
            "identity",
            "copyright",
            "role",
            "body",
            "hands",
            "handwear",
            "accessories",
            "props",
            "weapons",
            "extra",
        ],
    },
    "foot_detail": {
        "include": [
            "character",
            "identity",
            "copyright",
            "role",
            "body",
            "feet",
            "legwear",
            "footwear",
            "extra",
        ],
    },
    "object_focus": {
        "include": [
            "character",
            "identity",
            "copyright",
            "role",
            "accessories",
            "weapons",
            "props",
            "extra",
        ],
    },
}


def resolve_character_scope(
    *,
    action: NodeDocument | None,
    character: NodeDocument | None,
    character_scope: str | None,
) -> str:
    return (
        character_scope
        or (action.character_scope if action else None)
        or (character.character_scope if character else None)
        or "default"
    )


def character_positive(
    node: NodeDocument | None,
    character_scope: str | None,
) -> tuple[list[str], list[str], list[str]]:
    if node is None:
        return [], [], []
    if node.prompt.positive:
        included_roles: list[str] = []
        suppressed_roles: list[str] = []
        texts: list[str] = []
        for fragment in node.prompt.positive:
            role = fragment.role or "prompt"
            if fragment.applies_to(character_scope):
                texts.append(fragment.text)
                included_roles.append(role)
            else:
                suppressed_roles.append(role)
        return texts, dedupe(included_roles), dedupe(suppressed_roles)

    sections = list(node.tags.keys())
    include_sections = included_character_sections(sections, character_scope)
    include_set = set(include_sections)
    suppressed_sections = [section for section in sections if section not in include_set]
    texts: list[str] = []
    for section in include_sections:
        texts.extend(node.tags.get(section, []))
    return texts, include_sections, suppressed_sections


def node_positive(
    node: NodeDocument | None,
    character_scope: str | None,
) -> list[str]:
    if node is None:
        return []
    if node.kind == "character":
        return character_positive(node, character_scope)[0]
    if node.prompt.positive:
        return node.positive_texts(character_scope)
    return node.all_tags()


def node_negative(
    node: NodeDocument | None,
    character_scope: str | None,
) -> list[str]:
    if node is None:
        return []
    items: list[str] = []
    items.extend(node.negative_prompt)
    items.extend(node.negative_texts(character_scope))
    return items


def character_material(
    *,
    node: NodeDocument,
    ref: str,
    index: int,
    character_scope: str | None,
) -> dict[str, Any]:
    positive_tags, included, suppressed = character_positive(node, character_scope)
    return {
        "ref": ref,
        "id": node.id,
        "index": index,
        "used_sections": included,
        "suppressed_sections": suppressed,
        "positive_tags": positive_tags,
        "negative_tags": node_negative(node, character_scope),
    }


def included_character_sections(
    sections: list[str],
    character_scope: str | None,
) -> list[str]:
    policy = CHARACTER_SCOPE_POLICY.get(
        character_scope or "default",
        CHARACTER_SCOPE_POLICY["default"],
    )
    include = policy.get("include")
    if include is None:
        return sections
    include_set = set(include)
    return [section for section in sections if section in include_set]


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
