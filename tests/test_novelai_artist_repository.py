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
