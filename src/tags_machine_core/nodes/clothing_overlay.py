from __future__ import annotations

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.policies.rules.clothing import OUTFIT_SECTION_KEYS


def apply_clothing_overlay(
    character: NodeDocument,
    clothing: NodeDocument,
) -> NodeDocument:
    """将 clothing 节点的 tags 覆盖到 character 的衣装 sections 上。

    1. 移除 character.tags 中属于 OUTFIT_SECTION_KEYS 的所有 sections
    2. 对 role section 进行合并去重（保留角色原 role，并追加 clothing 的 role）
    3. 将 clothing.tags 的其余 sections 覆盖/合并进去
    4. 返回新的 NodeDocument（不修改原始对象）
    """
    merged_tags: dict[str, list[str]] = {}
    for section, values in character.tags.items():
        if section in OUTFIT_SECTION_KEYS:
            continue
        if section == "role":
            merged_role = list(values)
            for tag in clothing.tags.get("role", []):
                if tag not in merged_role:
                    merged_role.append(tag)
            merged_tags["role"] = merged_role
        else:
            merged_tags[section] = list(values)

    if "role" not in character.tags and "role" in clothing.tags:
        merged_tags["role"] = list(clothing.tags["role"])

    for section, values in clothing.tags.items():
        if section == "role":
            continue
        merged_tags[section] = list(values)

    merged_negative = list(character.negative_prompt)
    if clothing.negative_prompt:
        merged_negative.extend(clothing.negative_prompt)

    overlay_sections = [section for section in clothing.tags.keys() if section != "role"]
    new_composition = dict(character.composition or {})
    existing_overlay = list(new_composition.get("clothing_overlay_sections") or [])
    for sec in overlay_sections:
        if sec not in existing_overlay:
            existing_overlay.append(sec)
    new_composition["clothing_overlay_sections"] = existing_overlay

    return character.model_copy(
        update={
            "tags": merged_tags,
            "negative_prompt": merged_negative,
            "composition": new_composition,
        }
    )
