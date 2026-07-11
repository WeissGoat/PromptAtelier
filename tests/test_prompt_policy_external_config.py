import unittest

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet
from tags_machine_core.policies import PromptPolicyProvider
from tags_machine_core.services.generation_service import GenerationService


class PromptPolicyExternalConfigTest(unittest.TestCase):
    def test_partial_override_keeps_default_rules(self):
        config = PromptPolicyProvider().resolve(
            {
                "rules": {
                    "character_weight": {
                        "enabled": True,
                    }
                }
            }
        )

        self.assertTrue(config.rules["character_extension"].enabled)
        self.assertTrue(config.rules["character_weight"].enabled)
        self.assertEqual(config.options_for("character_weight")["level"], 2)
        self.assertEqual(config.options_for("character_weight")["style"], "numeric")
        self.assertEqual(config.options_for("character_weight")["numeric_weight"], 2.0)

    def test_order_override_changes_only_same_phase_order(self):
        service = GenerationService()
        character = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi_homura"]},
        )
        action = NodeDocument(kind="action", id="stand", tags={"action": ["standing"]})

        bundle = service.compose_nodes(
            character=character,
            action=action,
            prompt_policy={
                "rules": {
                    "clothing_policy": {
                        "order": {"after": ["visibility_policy"]},
                    }
                }
            },
        )

        order = bundle.meta.extra["policy"]["effective_rule_order"]
        self.assertLess(order.index("visibility_policy@v1"), order.index("clothing_policy@v2"))

    def test_character_weight_reaches_novelai_character_caption(self):
        service = GenerationService()
        character = NodeDocument(
            kind="character",
            id="homura",
            character_id="akemi_homura",
            tags={
                "character": ["akemi_homura"],
                "hair": ["black_hair"],
            },
        )
        action = NodeDocument(kind="action", id="stand", tags={"action": ["standing"]})
        nodes = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=character),
                ResolvedNode(role="action", ref="stand", index=0, node=action),
            ]
        )

        bundle = service.compose_resolved_nodes(
            nodes,
            prompt_policy={
                "rules": {
                    "character_weight": {
                        "enabled": True,
                    }
                }
            },
        )
        request = service.build_novelai_request(
            bundle,
            resolved_nodes=nodes,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto"}},
        )

        caption = request.params["v4_prompt"]["caption"]
        self.assertNotIn("akemi_homura", caption["base_caption"])
        self.assertEqual(
            caption["char_captions"][0]["char_caption"],
            "girl, 2.0::akemi_homura::",
        )


if __name__ == "__main__":
    unittest.main()
