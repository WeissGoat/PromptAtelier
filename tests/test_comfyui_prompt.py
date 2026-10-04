from __future__ import annotations

import unittest

from tags_machine_core.contracts import PromptBundle, PromptText
from tags_machine_core.renderers import ComfyUIRenderAdapter
from tags_machine_core.renderers.comfyui_prompt import novelai_to_comfyui_prompt


def _artist(**renderer_fields) -> dict:
    return {
        "renderers": {
            "comfyui": {
                "workflow": "w",
                "workflow_json": {
                    "1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                    "3": {"class_type": "EmptyLatentImage", "inputs": {"width": 0, "height": 0}},
                    "4": {"class_type": "KSampler", "inputs": {"seed": 0}},
                },
                "inputs": {
                    "positive_prompt": "1.inputs.text",
                    "negative_prompt": "2.inputs.text",
                    "width": "3.inputs.width",
                    "height": "3.inputs.height",
                    "seed": "4.inputs.seed",
                },
                **renderer_fields,
            }
        }
    }


class ComfyUIRendererPromptFormatTest(unittest.TestCase):
    bundle = PromptBundle(prompt=PromptText(positive="{{x}}, a_(b)", negative="[lowres]"))

    def test_renderer_converts_novelai_syntax_by_default(self):
        request = ComfyUIRenderAdapter().build_request(self.bundle, artist=_artist())

        self.assertEqual(request.prompt, "{{x}}, a_(b)")
        self.assertEqual(request.params["prompt_format"], "comfyui")
        self.assertEqual(request.params["node_overrides"]["1.inputs.text"], "(x:1.1), a_\\(b\\)")
        self.assertEqual(request.params["node_overrides"]["2.inputs.text"], "(lowres:0.95)")

    def test_novelai_prompt_format_passes_text_through(self):
        request = ComfyUIRenderAdapter().build_request(
            self.bundle, artist=_artist(prompt_format="novelai")
        )

        self.assertEqual(request.params["node_overrides"]["1.inputs.text"], "{{x}}, a_(b)")
        self.assertEqual(request.params["node_overrides"]["2.inputs.text"], "[lowres]")

    def test_renderer_picks_a_random_seed_when_none_or_negative(self):
        adapter = ComfyUIRenderAdapter()
        seeds = {adapter.build_request(self.bundle, artist=_artist()).seed for _ in range(5)}
        negative = adapter.build_request(self.bundle, seed=-1, artist=_artist())
        explicit = adapter.build_request(self.bundle, seed=42, artist=_artist())

        self.assertGreater(len(seeds), 1)
        self.assertTrue(all(0 <= seed <= 4294967295 for seed in seeds))
        self.assertGreaterEqual(negative.seed, 0)
        self.assertEqual(negative.params["node_overrides"]["4.inputs.seed"], negative.seed)
        self.assertEqual(explicit.seed, 42)

    def test_renderer_rejects_unknown_prompt_format(self):
        with self.assertRaises(ValueError):
            ComfyUIRenderAdapter().build_request(self.bundle, artist=_artist(prompt_format="a1111"))


class NovelAIToComfyUIPromptTest(unittest.TestCase):
    def test_converts_emphasis_weights_and_escapes_parentheses(self):
        self.assertEqual(
            novelai_to_comfyui_prompt(
                "{{alternative_clothing}}, {toeless legwear}, [simple background], "
                "1.2::cunyfunky::, akemi_homura_(magical_girl), black_hair"
            ),
            "(alternative_clothing:1.1), (toeless legwear:1.05), (simple background:0.95), "
            "(cunyfunky:1.2), akemi_homura_\\(magical_girl\\), black_hair",
        )

    def test_nesting_multiplies_and_cancels(self):
        self.assertEqual(novelai_to_comfyui_prompt("{{{x}}}"), "(x:1.16)")
        self.assertEqual(novelai_to_comfyui_prompt("[[x]]"), "(x:0.91)")
        self.assertEqual(novelai_to_comfyui_prompt("{[x]}"), "x")

    def test_numeric_weight_combines_with_braces(self):
        self.assertEqual(novelai_to_comfyui_prompt("1.2::{a}, b::, c"), "(a:1.26), (b:1.2), c")
        self.assertEqual(novelai_to_comfyui_prompt("-1::bad hands::, ok"), "(bad hands:-1), ok")

    def test_groups_keep_separators_outside(self):
        self.assertEqual(novelai_to_comfyui_prompt("{a, b}, c"), "(a, b:1.05), c")
        self.assertEqual(novelai_to_comfyui_prompt("{ spaced }"), " (spaced:1.05) ")

    def test_unbalanced_and_plain_text(self):
        self.assertEqual(novelai_to_comfyui_prompt("a}, {b"), "a, (b:1.05)")
        self.assertEqual(novelai_to_comfyui_prompt("tag_\\(x\\)"), "tag_\\(x\\)")
        self.assertEqual(novelai_to_comfyui_prompt("a, b"), "a, b")
        self.assertEqual(novelai_to_comfyui_prompt(""), "")


if __name__ == "__main__":
    unittest.main()
