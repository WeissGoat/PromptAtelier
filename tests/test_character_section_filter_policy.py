from __future__ import annotations

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet
from tags_machine_core.services.generation_service import GenerationService


def _resolved_nodes(*, action_repeats_copyright: bool = False) -> ResolvedNodeSet:
    character = NodeDocument(
        kind="character",
        id="homura",
        character_id="akemi_homura",
        tags={
            "character": ["akemi_homura"],
            "copyright": ["mahou_shoujo_madoka_magica"],
            "hair": ["black_hair"],
        },
    )
    action_tags = ["standing"]
    if action_repeats_copyright:
        action_tags.insert(0, "mahou_shoujo_madoka_magica")
    action = NodeDocument(
        kind="action",
        id="standing",
        tags={"default": action_tags},
        composition={
            "character_selection": {
                "default_selected_keys": ["character", "copyright", "hair"]
            }
        },
    )
    return ResolvedNodeSet(
        [
            ResolvedNode(role="character", ref="characters/homura", index=0, node=character),
            ResolvedNode(role="action", ref="actions/standing", index=0, node=action),
        ]
    )


def test_default_policy_blocks_character_copyright_and_updates_material() -> None:
    bundle = GenerationService().compose_resolved_nodes(_resolved_nodes())

    assert "mahou_shoujo_madoka_magica" not in bundle.prompt.positive
    assert "copyright" not in bundle.meta.composition.included_character_sections
    assert "copyright" in bundle.meta.composition.suppressed_character_sections

    material = bundle.meta.extra["character_materials"][0]
    assert material["used_sections"] == ["character", "hair"]
    assert "copyright" in material["suppressed_sections"]
    assert material["blocked_sections"] == ["copyright"]
    assert "mahou_shoujo_madoka_magica" not in material["positive_tags"]

    traces = bundle.meta.extra["policy_trace"]
    assert any(
        entry["rule"] == "character_section_filter@v1"
        and entry["action"] == "remove"
        and entry["token"] == "mahou_shoujo_madoka_magica"
        for entry in traces
    )


def test_policy_preserves_same_token_contributed_by_action() -> None:
    bundle = GenerationService().compose_resolved_nodes(
        _resolved_nodes(action_repeats_copyright=True)
    )

    assert bundle.prompt.positive.count("mahou_shoujo_madoka_magica") == 1
    assert "standing" in bundle.prompt.positive


def test_policy_can_be_disabled() -> None:
    bundle = GenerationService().compose_resolved_nodes(
        _resolved_nodes(),
        prompt_policy={
            "rules": {
                "character_section_filter": {
                    "enabled": False,
                }
            }
        },
    )

    assert "mahou_shoujo_madoka_magica" in bundle.prompt.positive
    material = bundle.meta.extra["character_materials"][0]
    assert "copyright" in material["used_sections"]
    assert "blocked_sections" not in material


def test_policy_preserves_negative_material_when_composer_did_not_create_one() -> None:
    nodes = _resolved_nodes()
    character = nodes.characters()[0].node.model_copy(
        update={"negative_prompt": ["red_glasses"]}
    )
    resolved = ResolvedNodeSet(
        [
            ResolvedNode(
                role="character",
                ref="characters/homura",
                index=0,
                node=character,
            ),
            nodes.actions()[0],
        ]
    )
    service = GenerationService()
    bundle = service.compose_nodes(
        character=character,
        action=resolved.actions()[0].node,
    )

    material = bundle.meta.extra["character_materials"][0]
    assert material["negative_tags"] == ["red_glasses"]
    assert "mahou_shoujo_madoka_magica" not in material["positive_tags"]
