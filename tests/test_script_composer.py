import unittest

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.nodes.models import NodeDocument


class ScriptComposerTest(unittest.TestCase):
    def test_compose_nodes_filters_character_sections_by_action_scope(self):
        character = NodeDocument.model_validate(
            {
                "schema": "tags-machine.character/v1",
                "kind": "character",
                "id": "homura",
                "tags": {
                    "character": ["akemi homura"],
                    "copyright": ["puella magi madoka magica"],
                    "hair": ["long black hair"],
                    "eyes": ["purple eyes"],
                    "upper_clothes": ["school uniform"],
                    "feet": ["bare soles"],
                    "footwear": ["shoes"],
                },
                "negative_prompt": ["extra toes"],
            }
        )
        action = NodeDocument.model_validate(
            {
                "schema": "tags-machine.action/v1",
                "kind": "action",
                "id": "foot_closeup",
                "tags": {
                    "action": ["foot focus", "soles toward viewer"],
                },
                "negative_prompt": ["face focus"],
                "character_scope": "foot_detail",
            }
        )

        bundle = ScriptComposer().compose_nodes(character=character, action=action)

        self.assertEqual(bundle.meta.composition.character_scope, "foot_detail")
        self.assertEqual(
            bundle.meta.composition.included_character_sections,
            ["character", "copyright", "feet", "footwear"],
        )
        self.assertEqual(
            bundle.meta.composition.suppressed_character_sections,
            ["hair", "eyes", "upper_clothes"],
        )
        self.assertIn("akemi homura", bundle.prompt.positive)
        self.assertIn("bare soles", bundle.prompt.positive)
        self.assertIn("foot focus", bundle.prompt.positive)
        self.assertIn("soles toward viewer", bundle.prompt.positive)
        self.assertNotIn("purple eyes", bundle.prompt.positive)
        self.assertNotIn("long black hair", bundle.prompt.positive)
        self.assertNotIn("school uniform", bundle.prompt.positive)
        self.assertIn("extra toes", bundle.prompt.negative)
        self.assertIn("face focus", bundle.prompt.negative)
        self.assertEqual(bundle.meta.character_ref, "homura")
        self.assertEqual(bundle.meta.action_ref, "foot_closeup")

    def test_compose_nodes_can_override_character_scope(self):
        character = NodeDocument.model_validate(
            {
                "schema": "tags-machine.character/v1",
                "kind": "character",
                "id": "homura",
                "tags": {
                    "character": ["akemi homura"],
                    "eyes": ["purple eyes"],
                    "feet": ["bare soles"],
                },
            }
        )

        bundle = ScriptComposer().compose_nodes(
            character=character,
            character_scope="face_detail",
        )

        self.assertEqual(bundle.meta.composition.character_scope, "face_detail")
        self.assertIn("purple eyes", bundle.prompt.positive)
        self.assertNotIn("bare soles", bundle.prompt.positive)

    def test_hand_detail_suppresses_feet_and_lower_body_sections(self):
        character = NodeDocument.model_validate(
            {
                "schema": "tags-machine.character/v1",
                "kind": "character",
                "id": "homura",
                "tags": {
                    "character": ["akemi homura"],
                    "hair": ["long black hair"],
                    "eyes": ["purple eyes"],
                    "hands": ["slender hands"],
                    "handwear": ["black gloves"],
                    "feet": ["bare soles"],
                    "footwear": ["shoes"],
                    "lower_clothes": ["black skirt"],
                },
            }
        )
        action = NodeDocument.model_validate(
            {
                "schema": "tags-machine.action/v1",
                "kind": "action",
                "id": "hand_closeup",
                "character_scope": "hand_detail",
                "tags": {"action": ["hand focus", "reaching toward viewer"]},
            }
        )

        bundle = ScriptComposer().compose_nodes(character=character, action=action)

        self.assertEqual(bundle.meta.composition.character_scope, "hand_detail")
        self.assertIn("slender hands", bundle.prompt.positive)
        self.assertIn("black gloves", bundle.prompt.positive)
        self.assertIn("hand focus", bundle.prompt.positive)
        self.assertNotIn("bare soles", bundle.prompt.positive)
        self.assertNotIn("shoes", bundle.prompt.positive)
        self.assertNotIn("black skirt", bundle.prompt.positive)
        self.assertIn("hands", bundle.meta.composition.included_character_sections)
        self.assertIn("handwear", bundle.meta.composition.included_character_sections)
        self.assertIn("feet", bundle.meta.composition.suppressed_character_sections)
        self.assertIn("footwear", bundle.meta.composition.suppressed_character_sections)
        self.assertIn("lower_clothes", bundle.meta.composition.suppressed_character_sections)

    def test_legacy_scoped_prompt_fragments_remain_supported(self):
        character = NodeDocument.model_validate(
            {
                "kind": "character",
                "id": "homura",
                "prompt": {
                    "positive": [
                        {"text": "akemi homura", "role": "identity", "include_scopes": ["*"]},
                        {"text": "purple eyes", "role": "eyes", "include_scopes": ["face_detail"]},
                        {"text": "bare soles", "role": "feet", "include_scopes": ["foot_detail"]},
                    ],
                },
            }
        )

        bundle = ScriptComposer().compose_nodes(character=character, body_scope="face_detail")

        self.assertEqual(bundle.meta.composition.character_scope, "face_detail")
        self.assertIn("purple eyes", bundle.prompt.positive)
        self.assertNotIn("bare soles", bundle.prompt.positive)

    def test_non_v1_shot_body_scope_does_not_drive_character_scope(self):
        character = NodeDocument.model_validate(
            {
                "schema": "tags-machine.character/v1",
                "kind": "character",
                "id": "homura",
                "tags": {
                    "character": ["akemi homura"],
                    "eyes": ["purple eyes"],
                    "feet": ["bare soles"],
                },
            }
        )
        action = NodeDocument.model_validate(
            {
                "schema": "tags-machine.action/v1",
                "kind": "action",
                "id": "legacy_shot_action",
                "tags": {"action": ["foot focus"]},
                "shot": {"body_scope": "foot_detail"},
            }
        )

        bundle = ScriptComposer().compose_nodes(character=character, action=action)

        self.assertEqual(bundle.meta.composition.character_scope, "default")
        self.assertIn("purple eyes", bundle.prompt.positive)
        self.assertIn("bare soles", bundle.prompt.positive)


if __name__ == "__main__":
    unittest.main()
