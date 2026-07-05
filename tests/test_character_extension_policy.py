import unittest

from tags_machine_core.composers import AgentComposer
from tags_machine_core.nodes.models import LegacyNodeMeta, NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet
from tags_machine_core.services.generation_service import GenerationService


def _character(extension_lines: list[str]) -> NodeDocument:
    return NodeDocument(
        kind="character",
        id="homura",
        identity_minimal=["character", "copyright"],
        tags={
            "character": ["akemi homura"],
            "copyright": ["mahou shoujo madoka magica"],
        },
        legacy=LegacyNodeMeta(
            raw_sections={
                "extension": extension_lines,
            }
        ),
    )


def _compose(character: NodeDocument, action: NodeDocument):
    nodes = ResolvedNodeSet(
        [
            ResolvedNode(role="character", ref="homura", index=0, node=character),
            ResolvedNode(role="action", ref=action.id, index=0, node=action),
        ]
    )
    return GenerationService().compose_resolved_nodes(
        nodes,
        prompt_policy={
            "enabled": True,
            "profile": "off",
            "enabled_rules": ["character_extension"],
            "apply_to": {"script": True},
        },
    )


class CharacterExtensionPolicyTest(unittest.TestCase):
    def test_adds_materials_and_applies_legacy_operations(self):
        character = _character(
            [
                "ext_legwear,argyle_legwear,pantyhose",
                "ext_weapon,shield,dark_orb_(madoka_magica),soul_gem,",
                "leg_wear, pantyhose|thighhighs, include_replace|pantyhose|black_pantyhose, add|argyle_legwear",
                "weapon, weapon|sword, include_replace|weapon|sword|gun, add_after|gun|weapon, add|gun|shield|",
            ]
        )
        action = NodeDocument(
            kind="action",
            id="leg_weapon",
            tags={"action": ["black pantyhose, weapon, lower body"]},
        )

        bundle = _compose(character, action)

        self.assertIn("akemi_homura", bundle.prompt.positive)
        self.assertIn("mahou_shoujo_madoka_magica", bundle.prompt.positive)
        self.assertIn("black_pantyhose", bundle.prompt.positive)
        self.assertIn("argyle_legwear", bundle.prompt.positive)
        self.assertIn("gun", bundle.prompt.positive)
        self.assertIn("shield", bundle.prompt.positive)
        self.assertIn("dark_orb_(madoka_magica)", bundle.prompt.positive)
        trace = bundle.meta.extra["policy_trace"]
        self.assertTrue(any(item["rule"].startswith("character_extension@") for item in trace))
        self.assertTrue(any(item["action"] == "include_replace" for item in trace))
        self.assertTrue(any(item["action"] == "add_material" for item in trace))

    def test_add_after_uses_legacy_last_argument_as_anchor(self):
        character = _character(
            [
                "shoes, shoes|footwear, add_after|high_heels|shoes",
            ]
        )
        action = NodeDocument(kind="action", id="shoe", tags={"action": ["shoes, standing"]})

        bundle = _compose(character, action)

        tokens = [part.strip() for part in bundle.prompt.positive.split(",")]
        self.assertEqual(tokens.index("high_heels"), tokens.index("shoes") + 1)

    def test_add_if_not_exist_uses_first_argument_as_target(self):
        character = _character(
            [
                "extend_func_pantyhose, pantyhose, add_if_not_exist|no shoes|high_heels",
            ]
        )
        action = NodeDocument(kind="action", id="pantyhose", tags={"action": ["pantyhose"]})

        bundle = _compose(character, action)

        self.assertIn("no_shoes", bundle.prompt.positive)

    def test_legacy_compat_profile_enables_character_extension_for_script_only(self):
        character = _character(
            [
                "ext_weapon,shield",
                "weapon, weapon, add|shield",
            ]
        )
        action = NodeDocument(kind="action", id="weapon", tags={"action": ["weapon"]})
        nodes = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=character),
                ResolvedNode(role="action", ref="weapon", index=0, node=action),
            ]
        )

        bundle = GenerationService().compose_resolved_nodes(
            nodes,
            prompt_policy={
                "enabled": True,
                "profile": "legacy_compat",
                "apply_to": {"script": True},
            },
        )

        self.assertIn("shield", bundle.prompt.positive)
        self.assertTrue(
            any(
                rule.startswith("character_extension@")
                for rule in bundle.meta.extra["policy"]["enabled_rules"]
            )
        )

    def test_agent_composer_still_bypasses_character_extension_policy(self):
        character = _character(["weapon, weapon, add|shield"])
        action = NodeDocument(kind="action", id="weapon", tags={"action": ["weapon"]})
        task = AgentComposer().build_task(character=character, action=action)

        bundle = AgentComposer().compose_from_result(task, {"positive": "weapon", "negative": ""})

        self.assertEqual(bundle.prompt.positive, "weapon")
        self.assertNotIn("policy", bundle.meta.extra)


if __name__ == "__main__":
    unittest.main()
