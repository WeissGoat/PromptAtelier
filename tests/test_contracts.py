import unittest

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


if __name__ == "__main__":
    unittest.main()
