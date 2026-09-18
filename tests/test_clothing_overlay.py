from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from tags_machine_core.batch.models import BatchSpec, NodeRef, SelectorSpec
from tags_machine_core.batch.planner import BatchPlanner
from tags_machine_core.batch.selectors import CharacterSelection, SelectorContext, expand_selector
from tags_machine_core.nodes.clothing_overlay import apply_clothing_overlay
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.services import GenerationJsonApi


class TestClothingOverlay(unittest.TestCase):
    def test_apply_clothing_overlay_basic(self):
        character = NodeDocument(
            schema="tags-machine.character/v1",
            kind="character",
            id="homura",
            tags={
                "character": ["akemi homura"],
                "hair": ["black hair", "long hair"],
                "eyes": ["purple eyes"],
                "upper_clothes": ["magical girl outfit", "capelet"],
                "lower_clothes": ["black skirt"],
                "shoes": ["black boots"],
                "accessories": ["glasses"],
            },
            negative_prompt=["glasses"],
        )
        clothing = NodeDocument(
            schema="tags-machine.clothing/v1",
            kind="clothing",
            id="school_uniform",
            tags={
                "upper_clothes": ["white shirt", "sailor collar"],
                "lower_clothes": ["blue pleated skirt"],
                "shoes": ["brown loafers"],
                "accessories": ["red ribbon"],
            },
            negative_prompt=["armor"],
        )

        merged = apply_clothing_overlay(character, clothing)

        # Original character is unchanged
        self.assertIn("magical girl outfit", character.tags["upper_clothes"])
        self.assertEqual(character.negative_prompt, ["glasses"])

        # Identity tags preserved
        self.assertEqual(merged.tags["character"], ["akemi homura"])
        self.assertEqual(merged.tags["hair"], ["black hair", "long hair"])
        self.assertEqual(merged.tags["eyes"], ["purple eyes"])

        # Outfit tags replaced
        self.assertEqual(merged.tags["upper_clothes"], ["white shirt", "sailor collar"])
        self.assertEqual(merged.tags["lower_clothes"], ["blue pleated skirt"])
        self.assertEqual(merged.tags["shoes"], ["brown loafers"])

        # Non-outfit section from clothing overwrites character section
        self.assertEqual(merged.tags["accessories"], ["red ribbon"])

        # Negative prompts merged
        self.assertEqual(merged.negative_prompt, ["glasses", "armor"])

    def test_apply_clothing_overlay_role_merge(self):
        # Case 1: Character has role, clothing has role -> merged & deduped, character role first
        character = NodeDocument(
            schema="tags-machine.character/v1",
            kind="character",
            id="cat_char",
            tags={
                "character": ["alice"],
                "role": ["cat_girl", "1girl"],
                "upper_clothes": ["old_dress"],
            },
        )
        clothing = NodeDocument(
            schema="tags-machine.clothing/v1",
            kind="clothing",
            id="suit",
            tags={
                "role": ["{{alternative_clothing}}", "1girl"],
                "upper_clothes": ["suit_jacket"],
            },
        )
        merged = apply_clothing_overlay(character, clothing)
        self.assertEqual(merged.tags["role"], ["cat_girl", "1girl", "{{alternative_clothing}}"])
        self.assertEqual(merged.tags["upper_clothes"], ["suit_jacket"])

        # Case 2: Character has no role, clothing has role -> clothing role used
        char_no_role = NodeDocument(
            schema="tags-machine.character/v1",
            kind="character",
            id="plain_char",
            tags={
                "character": ["bob"],
                "upper_clothes": ["tshirt"],
            },
        )
        merged2 = apply_clothing_overlay(char_no_role, clothing)
        self.assertEqual(merged2.tags["role"], ["{{alternative_clothing}}", "1girl"])

        # Case 3: Character has role, clothing has no role -> character role preserved
        clothing_no_role = NodeDocument(
            schema="tags-machine.clothing/v1",
            kind="clothing",
            id="plain_suit",
            tags={
                "upper_clothes": ["coat"],
            },
        )
        merged3 = apply_clothing_overlay(character, clothing_no_role)
        self.assertEqual(merged3.tags["role"], ["cat_girl", "1girl"])

    def test_json_api_compose_with_clothing_ref(self):
        api = GenerationJsonApi()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            char_dir = tmp_path / "homura"
            char_dir.mkdir()
            (char_dir / "meta.yaml").write_text(
                """
schema: tags-machine.character/v1
kind: character
id: homura
tags:
  character:
    - akemi homura
  hair:
    - black hair
  upper_clothes:
    - default outfit
""",
                encoding="utf-8",
            )

            clothing_dir = tmp_path / "swimsuit"
            clothing_dir.mkdir()
            (clothing_dir / "meta.yaml").write_text(
                """
schema: tags-machine.clothing/v1
kind: clothing
id: swimsuit
tags:
  full_body_clothes:
    - school swimsuit
""",
                encoding="utf-8",
            )

            # Compose without clothing
            bundle_no_clothing = api.compose({
                "nodes": [
                    {"role": "character", "ref": str(char_dir)},
                ],
                "character_scope": "full_body",
            })
            positive_no_clothing = bundle_no_clothing["prompt"]["positive"]
            self.assertIn("default_outfit", positive_no_clothing)
            self.assertNotIn("school_swimsuit", positive_no_clothing)

            # Compose with clothing_ref
            bundle_with_clothing = api.compose({
                "nodes": [
                    {
                        "role": "character",
                        "ref": str(char_dir),
                        "clothing_ref": str(clothing_dir),
                    },
                ],
                "character_scope": "full_body",
            })
            positive_with_clothing = bundle_with_clothing["prompt"]["positive"]
            self.assertNotIn("default_outfit", positive_with_clothing)
            self.assertIn("school_swimsuit", positive_with_clothing)
            self.assertIn("akemi_homura", positive_with_clothing)

    def test_clothing_overlay_not_suppressed_by_action_selected_keys(self):
        from tags_machine_core.composers import ScriptComposer

        character = NodeDocument(
            schema="tags-machine.character/v1",
            kind="character",
            id="homura",
            tags={
                "character": ["akemi homura"],
                "hair": ["black hair"],
                "eyes": ["purple eyes"],
                "upper_clothes": ["magical girl outfit"],
            },
        )
        clothing = NodeDocument(
            schema="tags-machine.clothing/v1",
            kind="clothing",
            id="sailor",
            tags={
                "upper_clothes": ["sailor shirt"],
                "lower_clothes": ["pleated skirt"],
            },
        )
        action = NodeDocument(
            schema="tags-machine.action/v1",
            kind="action",
            id="action1",
            tags={"action": ["sitting"]},
            character_scope="full_body",
            composition={
                "character_selection": {
                    "characters": [
                        {"selected_keys": ["character", "hair"]}
                    ]
                }
            },
        )

        merged = apply_clothing_overlay(character, clothing)
        bundle = ScriptComposer().compose_nodes(character=merged, action=action)
        positive = bundle.prompt.positive

        self.assertIn("akemi homura", positive)
        self.assertIn("black hair", positive)
        self.assertNotIn("purple eyes", positive)
        self.assertNotIn("magical girl outfit", positive)
        self.assertIn("sailor shirt", positive)
        self.assertIn("pleated skirt", positive)
        self.assertIn("upper_clothes", bundle.meta.composition.included_character_sections)
        self.assertIn("lower_clothes", bundle.meta.composition.included_character_sections)
        self.assertNotIn("upper_clothes", bundle.meta.composition.suppressed_character_sections)
        self.assertNotIn("lower_clothes", bundle.meta.composition.suppressed_character_sections)

    def test_clothing_overlay_not_suppressed_by_default_scope(self):
        from tags_machine_core.composers import ScriptComposer

        character = NodeDocument(
            schema="tags-machine.character/v1",
            kind="character",
            id="homura",
            tags={
                "character": ["akemi homura"],
                "hair": ["black hair"],
                "upper_clothes": ["magical girl outfit"],
            },
        )
        clothing = NodeDocument(
            schema="tags-machine.clothing/v1",
            kind="clothing",
            id="sailor",
            tags={
                "upper_clothes": ["sailor shirt"],
                "lower_clothes": ["pleated skirt"],
            },
        )
        action = NodeDocument(
            schema="tags-machine.action/v1",
            kind="action",
            id="default_scope_action",
            tags={"action": ["sitting"]},
            character_scope="default",
        )

        merged = apply_clothing_overlay(character, clothing)
        bundle = ScriptComposer().compose_nodes(character=merged, action=action)
        positive = bundle.prompt.positive

        self.assertIn("akemi homura", positive)
        self.assertIn("sailor shirt", positive)
        self.assertIn("pleated skirt", positive)
        self.assertIn("upper_clothes", bundle.meta.composition.included_character_sections)
        self.assertIn("lower_clothes", bundle.meta.composition.included_character_sections)
        self.assertNotIn("upper_clothes", bundle.meta.composition.suppressed_character_sections)
        self.assertNotIn("lower_clothes", bundle.meta.composition.suppressed_character_sections)

    def test_batch_selectors_and_planner_clothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            char_path = tmp_path / "char1"
            char_path.mkdir()
            (char_path / "meta.yaml").write_text(
                "schema: tags-machine.character/v1\nkind: character\nid: c1\ntags:\n  character: [c1]\n  upper_clothes: [shirt]\n",
                encoding="utf-8",
            )
            cloth_path1 = tmp_path / "uniform"
            cloth_path1.mkdir()
            (cloth_path1 / "meta.yaml").write_text(
                "schema: tags-machine.clothing/v1\nkind: clothing\nid: u1\ntags:\n  upper_clothes: [uniform]\n",
                encoding="utf-8",
            )
            cloth_path2 = tmp_path / "swimsuit"
            cloth_path2.mkdir()
            (cloth_path2 / "meta.yaml").write_text(
                "schema: tags-machine.clothing/v1\nkind: clothing\nid: s1\ntags:\n  full_body_clothes: [swimsuit]\n",
                encoding="utf-8",
            )

            context = SelectorContext(base_dir=tmp_path, collections={})

            # Test explicit refs with dict format
            spec_explicit = SelectorSpec(
                selector="explicit",
                refs=[
                    {"ref": str(char_path), "clothing": str(cloth_path1)},
                    {"ref": str(char_path), "clothing": str(cloth_path2)},
                ],
            )
            selections = expand_selector(role="character", spec=spec_explicit, context=context)
            self.assertEqual(len(selections), 2)
            self.assertIsInstance(selections[0], CharacterSelection)
            self.assertEqual(selections[0].clothing, str(cloth_path1))
            self.assertEqual(selections[1].clothing, str(cloth_path2))

            # Test planner product expansion
            batch_spec = BatchSpec.model_validate({
                "schema": "tags-machine-core.batch/v1",
                "name": "test-batch",
                "output_root": str(tmp_path / "outputs"),
                "defaults": {
                    "composer": "script",
                },
                "select": {
                    "characters": [spec_explicit.model_dump()],
                },
                "expand": {
                    "mode": "product",
                },
            })
            planner = BatchPlanner(base_dir=tmp_path)
            tasks = planner.plan(batch_spec)
            self.assertEqual(len(tasks), 2)

            # Verify task 0 has uniform clothing_ref
            char_node_0 = next(n for n in tasks[0].nodes if n.role == "character")
            self.assertEqual(char_node_0.clothing_ref, str(cloth_path1))

            # Verify task 1 has swimsuit clothing_ref
            char_node_1 = next(n for n in tasks[1].nodes if n.role == "character")
            self.assertEqual(char_node_1.clothing_ref, str(cloth_path2))

    def test_batch_executor_with_clothing_overlay(self):
        from tags_machine_core.batch.executor import BatchExecutor
        from tags_machine_core.config import AppConfig, LegacyConfig
        from tags_machine_core.nodes import NodeReader

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            char_path = tmp_path / "char1"
            char_path.mkdir()
            (char_path / "meta.yaml").write_text(
                """schema: tags-machine.character/v1
kind: character
id: c1
tags:
  character: [c1]
  upper_clothes: [original_shirt]
""",
                encoding="utf-8",
            )
            cloth_path = tmp_path / "cloth1"
            cloth_path.mkdir()
            (cloth_path / "meta.yaml").write_text(
                """schema: tags-machine.clothing/v1
kind: clothing
id: cloth1
tags:
  upper_clothes: [overlay_uniform]
""",
                encoding="utf-8",
            )

            planner = BatchPlanner(base_dir=tmp_path)
            spec = BatchSpec.model_validate({
                "schema": "tags-machine-core.batch/v1",
                "name": "exec-test",
                "output_root": str(tmp_path / "outputs"),
                "defaults": {"composer": "script"},
                "select": {
                    "characters": [
                        {
                            "selector": "explicit",
                            "refs": [{"ref": str(char_path), "clothing": str(cloth_path)}],
                        }
                    ]
                },
            })
            tasks = planner.plan(spec)
            self.assertEqual(len(tasks), 1)

            config = AppConfig(legacy=LegacyConfig(tags_machine_root=str(tmp_path), design_root=str(tmp_path)))
            reader = NodeReader()
            executor = BatchExecutor(node_reader=reader)
            resolved = executor._resolved_nodes(tasks[0], config=config)

            characters = resolved.characters()
            self.assertEqual(len(characters), 1)
            char_tags = characters[0].node.tags
            self.assertIn("overlay_uniform", char_tags["upper_clothes"])
            self.assertNotIn("original_shirt", char_tags["upper_clothes"])


if __name__ == "__main__":
    unittest.main()
