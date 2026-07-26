import tempfile
import unittest
from pathlib import Path

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.nodes import NovelAIArtistRepository
from tools.legacy_migration import migrate_legacy_artist_tags
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.renderers import NovelAIRenderAdapter


class NovelAIStyleTest(unittest.TestCase):
    def test_legacy_style_repository_can_load_node_document(self):
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
gen_json, {"model": "nai-diffusion-4-5-full", "sampler": "k_euler_ancestral", "reference_image_multiple": ["abc"]}
not_quality_prompts
""".strip(),
                encoding="utf-8",
            )

            node = NovelAIArtistRepository(design_root).load_node("sample_style")

            self.assertEqual(node.kind, "artist")
            self.assertEqual(node.id, "sample_style")
            novelai = node.renderers["novelai"]
            self.assertTrue(novelai["legacy_compat"])
            self.assertFalse(novelai["include_common_tags"])
            self.assertEqual(novelai["prompt_prefix"], ["style prefix", "style suffix, best quality"])
            self.assertEqual(novelai["prompt_suffix"], [])
            self.assertEqual(novelai["negative_prompt"], ["lowres, bad anatomy"])
            self.assertEqual(novelai["after_negative_prompt"], ["extra fingers"])
            self.assertEqual(novelai["params"]["reference_image_multiple"], ["abc"])

    def test_novelai_adapter_builds_complete_v45_default_params(self):
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, foot focus",
            negative="bad feet",
        )

        request = NovelAIRenderAdapter().build_request(
            bundle,
            seed=123,
            width=832,
            height=1216,
        )

        params = request.params
        self.assertEqual(request.model, "nai-diffusion-4-5-full")
        self.assertEqual(params["params_version"], 1)
        self.assertEqual(params["width"], 832)
        self.assertEqual(params["height"], 1216)
        self.assertEqual(params["scale"], 5.0)
        self.assertEqual(params["sampler"], "k_euler")
        self.assertEqual(params["steps"], 28)
        self.assertEqual(params["seed"], 123)
        self.assertEqual(params["n_samples"], 1)
        self.assertEqual(params["ucPreset"], 3)
        self.assertFalse(params["qualityToggle"])
        self.assertFalse(params["sm"])
        self.assertFalse(params["sm_dyn"])
        self.assertFalse(params["dynamic_thresholding"])
        self.assertEqual(params["controlnet_strength"], 1.0)
        self.assertFalse(params["legacy"])
        self.assertFalse(params["add_original_image"])
        self.assertEqual(params["cfg_rescale"], 0.0)
        self.assertEqual(params["noise_schedule"], "native")
        self.assertFalse(params["legacy_v3_extend"])
        self.assertEqual(params["uncond_scale"], 0.0)
        self.assertEqual(params["prompt"], request.prompt)
        self.assertEqual(params["negative_prompt"], request.negative_prompt)
        self.assertEqual(params["reference_image_multiple"], [])
        self.assertEqual(params["reference_strength_multiple"], [])
        self.assertEqual(params["reference_information_extracted_multiple"], [])
        self.assertEqual(params["director_reference_images"], [])
        self.assertEqual(params["extra_noise_seed"], 123)
        self.assertEqual(params["v4_prompt"]["caption"]["base_caption"], request.prompt)
        self.assertEqual(
            params["v4_negative_prompt"]["caption"]["base_caption"],
            request.negative_prompt,
        )
        self.assertFalse(params["v4_prompt"]["use_coords"])
        self.assertFalse(params["v4_prompt"]["use_order"])
        self.assertEqual(params["v4_prompt"]["caption"]["char_captions"], [])
        self.assertNotIn("prefer_brownian", params)
        self.assertNotIn("deliberate_euler_ancestral_bug", params)

    def test_novelai_adapter_generates_random_seed_when_seed_is_omitted(self):
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, foot focus",
            negative="bad feet",
        )

        first = NovelAIRenderAdapter().build_request(bundle)
        second = NovelAIRenderAdapter().build_request(bundle)

        self.assertIsInstance(first.params["seed"], int)
        self.assertIsInstance(second.params["seed"], int)
        self.assertEqual(first.params["extra_noise_seed"], first.params["seed"])
        self.assertEqual(second.params["extra_noise_seed"], second.params["seed"])
        self.assertNotEqual(first.params["seed"], second.params["seed"])

    def test_novelai_adapter_normalizes_ddim_sampler_for_v45(self):
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, foot focus",
            negative="bad feet",
        )

        request = NovelAIRenderAdapter().build_request(
            bundle,
            seed=123,
            params={"sampler": "ddim", "sm": True, "sm_dyn": True},
        )

        self.assertEqual(request.params["sampler"], "ddim_v3")
        self.assertFalse(request.params["sm"])
        self.assertFalse(request.params["sm_dyn"])
        self.assertNotIn("prefer_brownian", request.params)
        self.assertNotIn("deliberate_euler_ancestral_bug", request.params)

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

            style = NovelAIArtistRepository(design_root).load("sample_style")
            self.assertEqual(style.prompt_prefix, ["style prefix", "style suffix, best quality"])
            self.assertEqual(style.prompt_suffix, [])
            self.assertEqual(style.params["reference_image_multiple"], ["abc"])

            bundle = ScriptComposer().compose_full_prompt(
                prompt="akemi homura, foot focus",
                negative="bad feet",
            )
            request = NovelAIRenderAdapter().build_request(bundle, seed=123, artist=style)

            self.assertEqual(request.model, "nai-diffusion-4-5-full")
            self.assertIn("style prefix", request.prompt)
            self.assertIn("akemi homura,foot focus", request.prompt)
            self.assertIn("style suffix,best quality", request.prompt)
            self.assertIn("bad feet", request.negative_prompt)
            self.assertIn("lowres,bad anatomy", request.negative_prompt)
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

    def test_legacy_style_type_line_is_flag_not_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            style_dir = design_root / "\u753b\u98ce" / "typed_style"
            style_dir.mkdir(parents=True)
            (style_dir / "tags.txt").write_text(
                """
style prefix,
style suffix,
type, not_quailty_prompts, character_2_after_artist_1
=
origin_uc, lowres
""".strip(),
                encoding="utf-8",
            )

            style = NovelAIArtistRepository(design_root).load("typed_style")

            self.assertEqual(style.prompt_prefix, ["style prefix", "style suffix"])
            self.assertEqual(style.prompt_suffix, [])
            self.assertIn("not_quailty_prompts", style.flags)
            self.assertIn("character_2_after_artist_1", style.flags)
            self.assertNotIn("type", style.prompt_suffix)

            bundle = ScriptComposer().compose_full_prompt(
                prompt="akemi homura, foot focus",
            )
            request = NovelAIRenderAdapter().build_request(bundle, seed=123, artist=style)

            self.assertEqual(
                request.prompt,
                "style prefix,style suffix,akemi homura,foot focus,",
            )
            self.assertNotIn("type", request.prompt)
            self.assertNotIn("very aesthetic", request.prompt)

    def test_legacy_style_empty_first_line_keeps_second_line_as_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            style_dir = design_root / "\u753b\u98ce" / "suffix_style"
            style_dir.mkdir(parents=True)
            (style_dir / "tags.txt").write_text(
                """
,
style suffix,
=
origin_uc, lowres
""".strip(),
                encoding="utf-8",
            )

            style = NovelAIArtistRepository(design_root).load("suffix_style")

            self.assertEqual(style.prompt_prefix, ["style suffix"])
            self.assertEqual(style.prompt_suffix, [])

            bundle = ScriptComposer().compose_full_prompt(
                prompt="akemi homura, foot focus",
            )
            request = NovelAIRenderAdapter().build_request(bundle, seed=123, artist=style)

            self.assertEqual(
                request.prompt,
                "style suffix,akemi homura,foot focus,::,very aesthetic,masterpiece,no text,",
            )

    def test_legacy_style_first_two_prompt_lines_are_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            style_dir = design_root / "\u753b\u98ce" / "three_line_style"
            style_dir.mkdir(parents=True)
            (style_dir / "tags.txt").write_text(
                """
line A,
line B,
line C,
=
origin_uc, lowres
""".strip(),
                encoding="utf-8",
            )

            style = NovelAIArtistRepository(design_root).load("three_line_style")

            self.assertEqual(style.prompt_prefix, ["line A", "line B"])
            self.assertEqual(style.prompt_suffix, ["line C"])

            bundle = ScriptComposer().compose_full_prompt(
                prompt="character and action",
            )
            request = NovelAIRenderAdapter().build_request(bundle, seed=123, artist=style)

            self.assertEqual(
                request.prompt,
                "line A,line B,character and action,line C,::,very aesthetic,masterpiece,no text,",
            )

    def test_legacy_movie_style_cleans_selected_artist_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            style_dir = design_root / "\u753b\u98ce" / "\u52a8\u753b_\u7535\u5f71\u611f_\u65392"
            style_dir.mkdir(parents=True)
            (style_dir / "tags.txt").write_text(
                """
wlop,artist:morikura_en,artist:ogipote, artist:ciloranko, anime style, High_contrast / Perfect_lighting / etc
dramatic lighting on characters
=
alias_name, \u9ed8\u8ba4
""".strip(),
                encoding="utf-8",
            )
            style = NovelAIArtistRepository(design_root).load("\u52a8\u753b_\u7535\u5f71\u611f_\u65392")
            bundle = ScriptComposer().compose_full_prompt(
                prompt="1girl, akemi homura, standing",
            )

            request = NovelAIRenderAdapter().build_request(bundle, seed=123, artist=style)

            self.assertEqual(
                request.prompt,
                "wlop,artist:ogipote,artist:ciloranko,anime style,"
                "High_contrast / Perfect_lighting / etc,dramatic lighting on characters,"
                "1girl,akemi homura,standing,::,very aesthetic,"
                "masterpiece,no text,",
            )

    def test_migrated_legacy_style_node_matches_tags_txt_novelai_request(self):
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
gen_json, {"model": "nai-diffusion-4-5-full", "sampler": "k_euler_ancestral", "noise_schedule": "karras", "steps": 28, "scale": 5.0, "reference_image_multiple": ["abc"], "reference_strength_multiple": [0.2], "reference_information_extracted_multiple": [0.8]}
not_quality_prompts
""".strip(),
                encoding="utf-8",
            )

            legacy_style = NovelAIArtistRepository(design_root).load("sample_style")
            migrated_node = NodeDocument.model_validate(
                migrate_legacy_artist_tags(style_dir, node_id="sample_style")
            )
            bundle = ScriptComposer().compose_full_prompt(
                prompt="akemi homura, foot focus",
                negative="bad feet",
            )

            legacy_request = NovelAIRenderAdapter().build_request(
                bundle,
                seed=123,
                artist=legacy_style,
            )
            migrated_request = NovelAIRenderAdapter().build_request(
                bundle,
                seed=123,
                artist=migrated_node,
            )

            self.assertEqual(migrated_node.renderers["novelai"]["include_common_tags"], False)
            self.assertEqual(migrated_node.renderers["novelai"]["legacy_compat"], True)
            self.assertEqual(migrated_request.prompt, legacy_request.prompt)
            self.assertEqual(migrated_request.negative_prompt, legacy_request.negative_prompt)
            self.assertEqual(migrated_request.model, legacy_request.model)
            for key in (
                "prompt",
                "negative_prompt",
                "sampler",
                "noise_schedule",
                "steps",
                "scale",
                "seed",
                "extra_noise_seed",
                "reference_image_multiple",
                "reference_strength_multiple",
                "reference_information_extracted_multiple",
                "v4_prompt",
                "v4_negative_prompt",
                "prefer_brownian",
                "deliberate_euler_ancestral_bug",
            ):
                self.assertEqual(migrated_request.params.get(key), legacy_request.params.get(key))

    def test_structured_style_node_builds_novelai_request(self):
        style = NodeDocument.model_validate(
            {
                "schema": "tags-machine.artist/v1",
                "kind": "artist",
                "id": "anime_comfy",
                "tags": {
                    "artist": ["anime style", "clean lineart"],
                    "quality": ["{best quality}"],
                },
                "negative_prompt": ["lowres"],
                "renderers": {
                    "novelai": {
                        "prompt_prefix": ["style prefix"],
                        "prompt_suffix": ["style suffix"],
                        "negative_prompt": ["bad anatomy"],
                        "after_negative_prompt": ["extra fingers"],
                        "params": {
                            "model": "nai-diffusion-4-5-full",
                            "sampler": "k_euler_ancestral",
                            "noise_schedule": "karras",
                            "steps": 30,
                            "scale": 5.5,
                            "reference_image_multiple": ["abc"],
                            "reference_strength_multiple": [0.25],
                            "reference_information_extracted_multiple": [0.6],
                        },
                    }
                },
            }
        )
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, foot focus",
            negative="bad feet",
        )

        request = NovelAIRenderAdapter().build_request(bundle, seed=321, artist=style)

        self.assertEqual(request.model, "nai-diffusion-4-5-full")
        self.assertEqual(request.params["steps"], 30)
        self.assertEqual(request.params["scale"], 5.5)
        self.assertEqual(request.params["reference_image_multiple"], ["abc"])
        self.assertEqual(request.params["reference_strength_multiple"], [0.25])
        self.assertEqual(request.params["reference_information_extracted_multiple"], [0.6])
        self.assertIn("style prefix", request.prompt)
        self.assertIn("akemi homura, foot focus", request.prompt)
        self.assertIn("anime style", request.prompt)
        self.assertIn("{best quality}", request.prompt)
        self.assertIn("style suffix", request.prompt)
        self.assertIn("bad feet", request.negative_prompt)
        self.assertIn("lowres", request.negative_prompt)
        self.assertIn("bad anatomy", request.negative_prompt)
        self.assertIn("extra fingers", request.negative_prompt)
        self.assertEqual(request.params["v4_prompt"]["caption"]["base_caption"], request.prompt)
        self.assertEqual(
            request.params["v4_negative_prompt"]["caption"]["base_caption"],
            request.negative_prompt,
        )
        self.assertTrue(request.params["prefer_brownian"])


if __name__ == "__main__":
    unittest.main()
