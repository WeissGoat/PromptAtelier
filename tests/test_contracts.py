import unittest

from tags_machine_core.contracts import PromptBundle
from tags_machine_core.composers import ScriptComposer
from tags_machine_core.renderers import NovelAIRenderAdapter


class ContractsTest(unittest.TestCase):
    def test_compose_and_render_request(self):
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, foot focus",
            style_ref="20260412_2",
        )
        self.assertEqual(bundle.prompt.positive, "akemi homura, foot focus")
        self.assertEqual(bundle.meta.style_ref, "20260412_2")
        self.assertTrue(bundle.cache.cache_key.startswith("sha256:"))

        request = NovelAIRenderAdapter().build_request(bundle, seed=123)
        self.assertEqual(request.backend, "novelai")
        self.assertEqual(request.seed, 123)
        self.assertEqual(request.params["extra_noise_seed"], 123)
        self.assertIn("v4_prompt", request.params)
        self.assertEqual(request.meta["style_ref"], "20260412_2")

    def test_prompt_bundle_meta_excludes_shot_and_constraints_contract_fields(self):
        bundle = PromptBundle.model_validate(
            {
                "prompt": {
                    "positive": "akemi homura, foot focus",
                    "negative": "bad anatomy",
                },
                "meta": {
                    "character_ref": "homura",
                    "action_ref": "foot_closeup",
                    "shot": {"body_scope": "foot_detail"},
                    "constraints": {"forbidden_parts": ["eyes"]},
                    "composition": {
                        "character_scope": "foot_detail",
                        "included_character_sections": ["character", "feet"],
                        "suppressed_character_sections": ["eyes", "upper_clothes"],
                    },
                },
            }
        )

        meta = bundle.model_dump(mode="json", by_alias=True)["meta"]
        self.assertEqual(meta["action_ref"], "foot_closeup")
        self.assertEqual(meta["composition"]["character_scope"], "foot_detail")
        self.assertNotIn("shot", meta)
        self.assertNotIn("constraints", meta)


if __name__ == "__main__":
    unittest.main()
