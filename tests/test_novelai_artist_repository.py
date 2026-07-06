import tempfile
import unittest
from pathlib import Path

from tags_machine_core.nodes import NovelAIArtistRepository, migrate_legacy_artist_tags


class NovelAIArtistRepositoryTest(unittest.TestCase):
    def test_runtime_loader_uses_first_gen_json_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            artist_dir = design_root / "\u753b\u98ce" / "multi_json_artist"
            artist_dir.mkdir(parents=True)
            (artist_dir / "tags.txt").write_text(
                """
artist prefix,
=
gen_json, {"sampler": "k_euler", "steps": 28, "reference_strength_multiple": [0.16]}
gen_json, {"sampler": "k_dpmpp_2m", "steps": 40, "reference_strength_multiple": [0.24]}
""".strip(),
                encoding="utf-8",
            )

            artist = NovelAIArtistRepository(design_root).load("multi_json_artist")

            self.assertEqual(artist.params["sampler"], "k_euler")
            self.assertEqual(artist.params["steps"], 28)
            self.assertEqual(artist.params["reference_strength_multiple"], [0.16])

    def test_runtime_loader_reads_legacy_gen_param(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            artist_dir = design_root / "\u753b\u98ce" / "legacy_param_artist"
            artist_dir.mkdir(parents=True)
            (artist_dir / "tags.txt").write_text(
                """
artist prefix,
=
gen_param, 'model': 'nai-diffusion-4-5-full', 'sampler': 'k_dpmpp_2m', 'steps': 26, 'scale': 7.0, 'cfg_rescale': 0.3, 'dynamic_thresholding': False, 'reference_image_multiple': ['abc']
""".strip(),
                encoding="utf-8",
            )

            artist = NovelAIArtistRepository(design_root).load("legacy_param_artist")

            self.assertEqual(artist.params["model"], "nai-diffusion-4-5-full")
            self.assertEqual(artist.params["sampler"], "k_dpmpp_2m")
            self.assertEqual(artist.params["steps"], 26)
            self.assertEqual(artist.params["scale"], 7.0)
            self.assertEqual(artist.params["cfg_rescale"], 0.3)
            self.assertIs(artist.params["dynamic_thresholding"], False)
            self.assertEqual(artist.params["reference_image_multiple"], ["abc"])

    def test_runtime_loader_filters_legacy_extension_params_without_equals_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            artist_dir = design_root / "\u753b\u98ce" / "inline_ext_artist"
            artist_dir.mkdir(parents=True)
            (artist_dir / "tags.txt").write_text(
                """
artist prefix,
style suffix,
origin_uc, lowres, bad anatomy
origin_clear:old copied prompt
gen_json, {"sampler": "k_euler", "steps": 28}
""".strip(),
                encoding="utf-8",
            )

            artist = NovelAIArtistRepository(design_root).load("inline_ext_artist")
            prompt = "\n".join(artist.prompt_prefix + artist.prompt_suffix)

            self.assertEqual(artist.prompt_prefix, ["artist prefix", "style suffix"])
            self.assertEqual(artist.prompt_suffix, [])
            self.assertEqual(artist.negative_prompt, "lowres, bad anatomy")
            self.assertEqual(artist.params["sampler"], "k_euler")
            self.assertEqual(artist.params["steps"], 28)
            self.assertNotIn("origin_uc", prompt)
            self.assertNotIn("origin_clear", prompt)
            self.assertNotIn("gen_json", prompt)

    def test_runtime_loader_treats_equals_prefix_as_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            artist_dir = design_root / "\u753b\u98ce" / "equals_prefix_artist"
            artist_dir.mkdir(parents=True)
            (artist_dir / "tags.txt").write_text(
                """
artist prefix,
= origin_uc, lowres
after_uc, extra fingers
""".strip(),
                encoding="utf-8",
            )

            artist = NovelAIArtistRepository(design_root).load("equals_prefix_artist")
            prompt = "\n".join(artist.prompt_prefix + artist.prompt_suffix)

            self.assertEqual(artist.prompt_prefix, ["artist prefix"])
            self.assertEqual(artist.prompt_suffix, [])
            self.assertEqual(artist.negative_prompt, "lowres")
            self.assertEqual(artist.after_negative_prompt, "extra fingers")
            self.assertNotIn("origin_uc", prompt)
            self.assertNotIn("after_uc", prompt)

    def test_migration_uses_first_gen_json_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            artist_dir = Path(tmp) / "multi_json_artist"
            artist_dir.mkdir()
            (artist_dir / "tags.txt").write_text(
                """
artist prefix,
=
gen_json, {"sampler": "k_euler", "steps": 28, "reference_strength_multiple": [0.16]}
gen_json, {"sampler": "k_dpmpp_2m", "steps": 40, "reference_strength_multiple": [0.24]}
""".strip(),
                encoding="utf-8",
            )

            node = migrate_legacy_artist_tags(artist_dir)
            params = node["renderers"]["novelai"]["params"]

            self.assertEqual(params["sampler"], "k_euler")
            self.assertEqual(params["steps"], 28)
            self.assertEqual(params["reference_strength_multiple"], [0.16])


if __name__ == "__main__":
    unittest.main()
