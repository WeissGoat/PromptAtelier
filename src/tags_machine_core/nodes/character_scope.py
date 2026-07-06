from __future__ import annotations

from typing import Any

from tags_machine_core.nodes.models import NodeDocument


IDENTITY_MINIMAL_SECTIONS = ["character", "role"]
IDENTITY_MINIMAL_POLICY = "__identity_minimal__"

CHARACTER_SCOPE_POLICY: dict[str, dict[str, list[str] | str | None]] = {
    "default": {"include": IDENTITY_MINIMAL_POLICY},
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
            "headwear",
            "ears",
            "upper_clothes",
            "full_body_clothes",
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
            "headwear",
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
            "headwear",
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
            "extra",
        ],
    },
    "object_focus": {
        "include": [
            "character",
            "identity",
            "copyright",
            "role",
            "hands",
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
    include_sections = included_character_sections(sections, character_scope, node=node)
    include_set = set(include_sections)
    suppressed_sections = [section for section in sections if section not in include_set]
    texts: list[str] = []
    for section in include_sections:
        texts.extend(node.tags.get(section, []))
    return texts, include_sections, suppressed_sections


def character_positive_with_selected_keys(
    node: NodeDocument | None,
    character_scope: str | None,
    selected_keys: list[str] | None,
) -> tuple[list[str], list[str], list[str]]:
    if node is None:
        return [], [], []
    normalized_keys = [str(key).strip() for key in selected_keys or [] if str(key).strip()]
    if not normalized_keys:
        return character_positive(node, character_scope)
    normalized_keys = dedupe(identity_minimal_sections(node) + normalized_keys)
    if node.prompt.positive:
        return _character_prompt_fragments_by_selected_keys(node, normalized_keys)
    sections = list(node.tags.keys())
    include_set = set(normalized_keys)
    included_sections = [section for section in sections if section in include_set]
    suppressed_sections = [section for section in sections if section not in include_set]
    texts: list[str] = []
    for section in included_sections:
        texts.extend(node.tags.get(section, []))
    return texts, included_sections, suppressed_sections


def _character_prompt_fragments_by_selected_keys(
    node: NodeDocument,
    selected_keys: list[str],
) -> tuple[list[str], list[str], list[str]]:
    include_set = set(selected_keys)
    texts: list[str] = []
    included_roles: list[str] = []
    suppressed_roles: list[str] = []
    for fragment in node.prompt.positive:
        role = fragment.role or "prompt"
        if role in include_set:
            texts.append(fragment.text)
            included_roles.append(role)
        else:
            suppressed_roles.append(role)
    return texts, dedupe(included_roles), dedupe(suppressed_roles)


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
    *,
    node: NodeDocument | None = None,
) -> list[str]:
    policy = CHARACTER_SCOPE_POLICY.get(character_scope or "default")
    if policy is None:
        policy = CHARACTER_SCOPE_POLICY["default"]
    include = policy.get("include")
    if include == IDENTITY_MINIMAL_POLICY:
        include = identity_minimal_sections(node)
    if include is None:
        return sections
    include_set = set(include)
    return [section for section in sections if section in include_set]


def identity_minimal_sections(node: NodeDocument | None) -> list[str]:
    if node is not None and node.identity_minimal:
        return node.identity_minimal
    return IDENTITY_MINIMAL_SECTIONS


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
