import unittest

from tags_machine_core.composers import AgentComposer, ScriptComposer
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet
from tags_machine_core.policies import PromptPolicyConfig, PromptPolicyPipeline
from tags_machine_core.policies.tokens import parse_prompt_token
from tags_machine_core.services.json_api import GenerationJsonApi
from tags_machine_core.services.generation_service import GenerationService


class PromptPolicyTokenTest(unittest.TestCase):
    def test_parse_prompt_token_preserves_bracket_weight(self):
        token = parse_prompt_token("{{high heels}}")

        self.assertEqual(token.body, "high heels")
        self.assertEqual(token.canonical, "high_heels")
        self.assertEqual(token.render("underscore"), "{{high_heels}}")
        self.assertEqual(token.render("preserve"), "{{high heels}}")

    def test_parse_prompt_token_preserves_numeric_weight(self):
        token = parse_prompt_token("2.0::akemi homura::")

        self.assertEqual(token.body, "akemi homura")
        self.assertEqual(token.canonical, "akemi_homura")
        self.assertEqual(token.render("underscore"), "2.0::akemi_homura::")


class PromptPolicyPipelineTest(unittest.TestCase):
    def test_policy_disabled_is_noop(self):
        bundle = ScriptComposer().compose_full_prompt("high heels, barefoot")

        result = PromptPolicyPipeline().apply(bundle, config=PromptPolicyConfig(), target="full_prompt")

        self.assertIs(result, bundle)
        self.assertEqual(result.prompt.positive, "high heels, barefoot")
        self.assertNotIn("policy", result.meta.extra)

    def test_normalize_only_converts_spaces_and_dedupes(self):
        service = GenerationService()

        bundle = service.compose_full_prompt(
            "high heels, high_heels, 2.0::akemi homura::",
            prompt_policy={
                "enabled": True,
                "profile": "normalize_only",
                "apply_to": {"full_prompt": True},
            },
        )

        self.assertEqual(bundle.prompt.positive, "high_heels, 2.0::akemi_homura::")
        self.assertTrue(bundle.meta.extra["policy"]["template"].endswith("normalize_only"))
        self.assertTrue(bundle.meta.extra["policy_trace"])

    def test_tag_conflict_removes_footwear_for_barefoot(self):
        service = GenerationService()

        bundle = service.compose_full_prompt(
            "bare feet, high heels, socks, toeless legwear",
            prompt_policy={
                "enabled": True,
                "profile": "balanced",
                "apply_to": {"full_prompt": True},
            },
        )

        self.assertIn("bare_feet", bundle.prompt.positive)
        self.assertNotIn("high_heels", bundle.prompt.positive)
        self.assertNotIn("socks", bundle.prompt.positive)
        self.assertIn("toeless_legwear", bundle.prompt.positive)

    def test_character_count_uses_resolved_character_nodes(self):
        homura = NodeDocument(kind="character", id="homura", tags={"character": ["akemi homura"]})
        madoka = NodeDocument(kind="character", id="madoka", tags={"character": ["kaname madoka"]})
        action = NodeDocument(kind="action", id="stand", tags={"action": ["standing"]})
        nodes = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=homura),
                ResolvedNode(role="character", ref="madoka", index=1, node=madoka),
                ResolvedNode(role="action", ref="stand", index=0, node=action),
            ]
        )

        bundle = GenerationService().compose_resolved_nodes(
            nodes,
            prompt_policy={
                "enabled": True,
                "profile": "balanced",
                "apply_to": {"script": True},
            },
        )

        self.assertTrue(bundle.prompt.positive.startswith("2girls,"))

    def test_clothing_and_visibility_enforce_for_script_policy(self):
        character = NodeDocument(
            kind="character",
            id="homura",
            tags={
                "character": ["akemi homura"],
                "hair": ["long black hair"],
                "eyes": ["purple eyes"],
                "upper_clothes": ["school uniform"],
                "feet": ["bare feet"],
            },
        )
        action = NodeDocument(
            kind="action",
            id="foot",
            tags={"action": ["foot focus, nude"]},
            character_scope="foot_detail",
        )

        bundle = GenerationService().compose_nodes(
            character=character,
            action=action,
            prompt_policy={
                "enabled": True,
                "profile": "strict",
                "apply_to": {"script": True},
            },
        )

        self.assertIn("akemi_homura", bundle.prompt.positive)
        self.assertIn("bare_feet", bundle.prompt.positive)
        self.assertIn("foot_focus", bundle.prompt.positive)
        self.assertNotIn("purple_eyes", bundle.prompt.positive)
        self.assertNotIn("long_black_hair", bundle.prompt.positive)
        self.assertNotIn("school_uniform", bundle.prompt.positive)

    def test_clothing_policy_action_outfit_removes_character_clothes_only(self):
        character = NodeDocument(
            kind="character",
            id="homura",
            tags={
                "character": ["akemi homura"],
                "upper_clothes": ["school uniform"],
                "lower_clothes": ["pleated skirt"],
            },
        )
        action = NodeDocument(
            kind="action",
            id="kimono_action",
            tags={"action": ["kimono, wide sleeves, school uniform, standing"]},
            character_scope="full_body",
            clothing={
                "state": "specific_outfit",
                "action_outfit": True,
            },
        )

        bundle = GenerationService().compose_nodes(
            character=character,
            action=action,
            prompt_policy={
                "enabled": True,
                "profile": "strict",
                "apply_to": {"script": True},
            },
        )

        self.assertIn("akemi_homura", bundle.prompt.positive)
        self.assertIn("kimono", bundle.prompt.positive)
        self.assertIn("wide_sleeves", bundle.prompt.positive)
        self.assertIn("school_uniform", bundle.prompt.positive)
        self.assertNotIn("pleated_skirt", bundle.prompt.positive)
        trace = bundle.meta.extra["policy_trace"]
        clothing_trace = [item for item in trace if item["rule"].startswith("clothing_policy")]
        self.assertEqual(
            [item["token"] for item in clothing_trace if item["action"] == "remove"],
            ["school_uniform", "pleated_skirt"],
        )

    def test_clothing_policy_nude_removes_character_default_clothes(self):
        character = NodeDocument(
            kind="character",
            id="homura",
            tags={
                "character": ["akemi homura"],
                "upper_clothes": ["school uniform"],
                "lower_clothes": ["pleated skirt"],
            },
        )
        action = NodeDocument(
            kind="action",
            id="nude_action",
            tags={"action": ["nude, standing"]},
            character_scope="full_body",
            clothing={
                "state": "nude",
                "action_outfit": False,
            },
        )

        bundle = GenerationService().compose_nodes(
            character=character,
            action=action,
            prompt_policy={
                "enabled": True,
                "profile": "strict",
                "apply_to": {"script": True},
            },
        )

        self.assertIn("nude", bundle.prompt.positive)
        self.assertNotIn("school_uniform", bundle.prompt.positive)
        self.assertNotIn("pleated_skirt", bundle.prompt.positive)

    def test_clothing_policy_clothed_state_is_noop(self):
        character = NodeDocument(
            kind="character",
            id="homura",
            tags={
                "character": ["akemi homura"],
                "upper_clothes": ["school uniform"],
            },
        )
        action = NodeDocument(
            kind="action",
            id="clothed_action",
            tags={"action": ["standing"]},
            character_scope="full_body",
            clothing={
                "state": "clothed",
                "action_outfit": False,
            },
        )

        bundle = GenerationService().compose_nodes(
            character=character,
            action=action,
            prompt_policy={
                "enabled": True,
                "profile": "strict",
                "apply_to": {"script": True},
            },
        )

        self.assertIn("school_uniform", bundle.prompt.positive)
        self.assertFalse(
            any(
                item["rule"].startswith("clothing_policy")
                for item in bundle.meta.extra["policy_trace"]
            )
        )

    def test_clothing_policy_removes_character_prompt_fragments_by_role(self):
        character = NodeDocument(
            kind="character",
            id="homura",
            prompt={
                "positive": [
                    {"text": "akemi homura", "role": "character"},
                    {"text": "school uniform", "role": "upper_clothes"},
                ]
            },
        )
        action = NodeDocument(
            kind="action",
            id="nude_action",
            tags={"action": ["nude, standing"]},
            character_scope="full_body",
            clothing={
                "state": "nude",
                "action_outfit": False,
            },
        )

        bundle = GenerationService().compose_nodes(
            character=character,
            action=action,
            prompt_policy={
                "enabled": True,
                "profile": "strict",
                "apply_to": {"script": True},
            },
        )

        self.assertIn("akemi_homura", bundle.prompt.positive)
        self.assertNotIn("school_uniform", bundle.prompt.positive)

    def test_agent_composer_is_unchanged_by_default(self):
        character = NodeDocument(kind="character", id="homura", tags={"character": ["akemi homura"]})
        action = NodeDocument(kind="action", id="foot", tags={"action": ["bare feet, high heels"]})
        task = AgentComposer().build_task(character=character, action=action)

        bundle = AgentComposer().compose_from_result(
            task,
            {"positive": "bare feet, high heels", "negative": ""},
        )

        self.assertEqual(bundle.prompt.positive, "bare feet, high heels")
        self.assertNotIn("policy", bundle.meta.extra)

    def test_json_api_accepts_prompt_policy_for_full_prompt(self):
        result = GenerationJsonApi().compose(
            {
                "prompt": "bare feet, high heels",
                "prompt_policy": {
                    "enabled": True,
                    "require": "balanced",
                    "apply_to": {"full_prompt": True},
                },
            }
        )

        self.assertEqual(result["prompt"]["positive"], "1girl, bare_feet")
        self.assertEqual(result["meta"]["extra"]["policy"]["target"], "full_prompt")

    def test_json_api_agent_ignores_prompt_policy_by_default(self):
        character = {"kind": "character", "id": "homura", "tags": {"character": ["akemi homura"]}}
        action = {"kind": "action", "id": "foot", "tags": {"action": ["bare feet, high heels"]}}

        result = GenerationJsonApi().compose_agent(
            {
                "nodes": [
                    {"role": "character", "ref": "homura", "node": character},
                    {"role": "action", "ref": "foot", "node": action},
                ],
                "prompt": "bare feet, high heels",
                "prompt_policy": {
                    "enabled": True,
                    "profile": "balanced",
                    "apply_to": {"agent": True},
                },
            }
        )

        self.assertEqual(result["prompt"]["positive"], "bare feet, high heels")
        self.assertNotIn("policy", result["meta"]["extra"])

    def test_generation_service_agent_path_logs_policy_bypass(self):
        class ExplodingPolicyPipeline:
            def apply(self, *args, **kwargs):
                raise AssertionError("AgentComposer path must not call PromptPolicyPipeline")

        character = NodeDocument(kind="character", id="homura", tags={"character": ["akemi homura"]})
        action = NodeDocument(kind="action", id="foot", tags={"action": ["bare feet, high heels"]})
        resolved_nodes = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=character),
                ResolvedNode(role="action", ref="foot", index=0, node=action),
            ]
        )
        service = GenerationService(policy_pipeline=ExplodingPolicyPipeline())

        with self.assertLogs("tags_machine_core", level="INFO") as logs:
            bundle = service.compose_resolved_nodes_with_agent(
                resolved_nodes,
                result={"positive": "bare feet, high heels", "negative": ""},
            )

        output = "\n".join(logs.output)
        self.assertIn("PromptPolicyPipeline bypassed by design", output)
        self.assertNotIn("PromptPolicyPipeline applying", output)
        self.assertEqual(bundle.prompt.positive, "bare feet, high heels")

    def test_json_api_compose_accepts_prompt_policy(self):
        from tags_machine_core.services.json_api import GenerationJsonApi

        result = GenerationJsonApi().compose(
            {
                "prompt": "bare feet, high heels",
                "prompt_policy": {
                    "enabled": True,
                    "profile": "balanced",
                    "apply_to": {"full_prompt": True},
                },
            }
        )

        self.assertEqual(result["prompt"]["positive"], "1girl, bare_feet")
        self.assertTrue(result["meta"]["extra"]["policy"]["template"].endswith("balanced"))

    def test_cli_policy_args_build_enabled_config(self):
        from argparse import Namespace
        from tags_machine_core.cli import _prompt_policy_from_args

        config = _prompt_policy_from_args(
            Namespace(
                prompt_policy_profile="normalize_only",
                prompt_policy_rule=[],
                no_prompt_policy_rule=["dedupe"],
                prompt_policy_output_style="preserve",
            ),
            target="full_prompt",
        )

        self.assertTrue(config["enabled"])
        self.assertTrue(config["apply_to"]["full_prompt"])
        self.assertFalse(config["apply_to"]["script"])
        self.assertEqual(config["require"], "normalize_only")
        self.assertEqual(config["disabled_rules"], ["dedupe"])
        self.assertEqual(config["normalization"]["output_style"], "preserve")


if __name__ == "__main__":
    unittest.main()
