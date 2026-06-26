import tempfile
import unittest
from pathlib import Path

from tags_machine_core.nodes import NodeReader
from tags_machine_core.nodes.migration import migrate_legacy_character_tags


class LegacyCNodeReaderTest(unittest.TestCase):
    def test_read_legacy_tags_txt_filters_cnode_type_and_extension_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "legacy_character"
            node_dir.mkdir()
            (node_dir / "tags.txt").write_text(
                """
akemi_homura, mahou_shoujo_madoka_magica
black_hair, long_hair
type,character_topic_limit,not_extend_tags
=
leg_wear, stirrup legwear|toeless legwear
shoes, shoes|boots|loafers
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)

            self.assertEqual(
                node.positive_texts(),
                [
                    "akemi_homura, mahou_shoujo_madoka_magica",
                    "black_hair, long_hair",
                ],
            )
            self.assertEqual(node.tags["legacy"], node.positive_texts())
            self.assertEqual(
                node.legacy.raw_sections["type"],
                ["type,character_topic_limit,not_extend_tags"],
            )
            self.assertEqual(
                node.legacy.raw_sections["extension"],
                [
                    "leg_wear, stirrup legwear|toeless legwear",
                    "shoes, shoes|boots|loafers",
                ],
            )
            self.assertNotIn("type,character_topic_limit,not_extend_tags", node.positive_texts())
            self.assertNotIn("leg_wear, stirrup legwear|toeless legwear", node.positive_texts())

    def test_read_legacy_tags_txt_moves_inline_extension_marker_to_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "legacy_action"
            node_dir.mkdir()
            (node_dir / "tags.txt").write_text(
                """
foot focus, toes focus
origin_uc, bad feet, extra toes
node_background, flower field
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)

            self.assertEqual(node.positive_texts(), ["foot focus, toes focus"])
            self.assertEqual(
                node.legacy.raw_sections["extension"],
                [
                    "origin_uc, bad feet, extra toes",
                    "node_background, flower field",
                ],
            )

    def test_read_legacy_action_tags_txt_moves_gen_json_to_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "legacy_action"
            node_dir.mkdir()
            (node_dir / "tags.txt").write_text(
                """
foot focus, toes focus
gen_json, {"sampler": "k_euler", "steps": 28}
origin_uc, bad feet
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)

            self.assertEqual(node.positive_texts(), ["foot focus, toes focus"])
            self.assertEqual(
                node.legacy.raw_sections["extension"],
                [
                    'gen_json, {"sampler": "k_euler", "steps": 28}',
                    "origin_uc, bad feet",
                ],
            )

    def test_read_legacy_tags_txt_treats_equals_prefix_as_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "legacy_character"
            node_dir.mkdir()
            (node_dir / "tags.txt").write_text(
                """
akemi_homura, mahou_shoujo_madoka_magica
= leg_wear, stirrup legwear|toeless legwear
shoes, shoes|boots|loafers
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)

            self.assertEqual(node.positive_texts(), ["akemi_homura, mahou_shoujo_madoka_magica"])
            self.assertEqual(
                node.legacy.raw_sections["extension"],
                [
                    "leg_wear, stirrup legwear|toeless legwear",
                    "shoes, shoes|boots|loafers",
                ],
            )

    def test_migrate_legacy_character_tags_filters_cnode_type_and_extension_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            character_dir = Path(tmp) / "old_character"
            character_dir.mkdir()
            (character_dir / "tags.txt").write_text(
                """
gotoh_hitori,bocchi_the_rock!
pink_hair,long_hair,blue_eyes
shuka_high_school_uniform,pink jacket
type,backboard,background,custom_topic_1
=
ext_legwear,black kneehighs
after_uc,turn pale
""".strip(),
                encoding="utf-8",
            )

            node = migrate_legacy_character_tags(character_dir)

            self.assertEqual(node["tags"]["character"], ["gotoh_hitori"])
            self.assertEqual(node["tags"]["copyright"], ["bocchi_the_rock!"])
            self.assertEqual(node["tags"]["hair"], ["pink_hair", "long_hair"])
            self.assertEqual(node["tags"]["eyes"], ["blue_eyes"])
            self.assertNotIn("type", node["tags"].get("unclassified", []))
            self.assertNotIn("backboard", node["tags"].get("unclassified", []))
            self.assertEqual(
                node["legacy"]["raw_sections"]["type"],
                ["type,backboard,background,custom_topic_1"],
            )
            self.assertEqual(
                node["legacy"]["raw_sections"]["extension"],
                ["ext_legwear,black kneehighs", "after_uc,turn pale"],
            )


if __name__ == "__main__":
    unittest.main()
