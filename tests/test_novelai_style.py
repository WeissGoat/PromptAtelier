import tempfile
import unittest
from pathlib import Path

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.renderers import NovelAIRenderAdapter, NovelAIStyleRepository


class NovelAIStyleTest(unittest.TestCase):
    def test_read_style_and_build_modern_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            style_dir = design_root / "\u753b\u98ce" / "sample_style"
            style_dir.mkdir(parents=True)
            (style_dir / "tags.txt").write_text(
                """
style prefix,
style suffix, best quality
=
origin_uc, lowres, bad anatomy
after_uc, extra fingers
gen_json, {"sampler": "k_euler_ancestral", "noise_schedule": "karras", "steps": 28, "scale": 5.0, "reference_image_multiple": ["abc"], "reference_strength_multiple": [0.2], "model": "nai-diffusion-4-5-full"}
""".strip(),
                encoding="utf-8",
            )

            style = NovelAIStyleRepository(design_root).load("sample_style")
            self.assertEqual(style.prompt_prefix, ["style prefix"])
            self.assertEqual(style.prompt_suffix, ["style suffix, best quality"])
            self.assertEqual(style.params["reference_image_multiple"], ["abc"])

            bundle = ScriptComposer().compose_full_prompt(
                prompt="akemi homura, foot focus",
                negative="bad feet",
                style_ref="sample_style",
            )
            request = NovelAIRenderAdapter().build_request(bundle, seed=123, style=style)

            self.assertEqual(request.model, "nai-diffusion-4-5-full")
            self.assertIn("style prefix", request.prompt)
            self.assertIn("akemi homura, foot focus", request.prompt)
            self.assertIn("style suffix, best quality", request.prompt)
            self.assertIn("bad feet", request.negative_prompt)
            self.assertIn("lowres, bad anatomy", request.negative_prompt)
            self.assertEqual(request.params["seed"], 123)
            self.assertEqual(request.params["extra_noise_seed"], 123)
            self.assertEqual(request.params["reference_image_multiple"], ["abc"])
            self.assertEqual(request.params["reference_strength_multiple"], [0.2])
            self.assertEqual(request.params["v4_prompt"]["caption"]["base_caption"], request.prompt)
            self.assertEqual(
                request.params["v4_negative_prompt"]["caption"]["base_caption"],
                request.negative_prompt,
            )
            self.assertTrue(request.params["prefer_brownian"])


if __name__ == "__main__":
    unittest.main()
