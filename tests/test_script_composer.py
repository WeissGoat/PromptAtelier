import unittest

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.nodes.models import NodeDocument


class ScriptComposerTest(unittest.TestCase):
    def test_compose_nodes_filters_character_fragments_by_action_scope(self):
        character = NodeDocument.model_validate(
            {
                "kind": "character",
                "id": "homura",
                "prompt": {
                    "positive": [
                        {"text": "akemi homura", "role": "identity", "include_scopes": ["*"]},
                        {
                            "text": "purple eyes",
                            "role": "eyes",
                            "exclude_scopes": ["foot_detail"],
                        },
                        {
                            "text": "black hair",
                            "role": "hair",
                            "exclude_scopes": ["foot_detail"],
                        },
                        {
                            "text": "school uniform",
                            "role": "clothing",
                            "exclude_scopes": ["foot_detail"],
                        },
                        {
                            "text": "bare soles",
                            "role": "feet",
                            "include_scopes": ["foot_detail"],
                        },
                    ],
                    "negative": [
                        {"text": "extra toes", "role": "anatomy"},
                    ],
                },
                "constraints": {
                    "required_parts": ["akemi homura"],
                    "forbidden_parts": ["purple eyes"],
                },
            }
        )
        action = NodeDocument.model_validate(
            {
                "kind": "action",
                "id": "foot_closeup",
                "shot": {"framing": "extreme close-up", "body_scope": "foot_detail"},
                "prompt": {
                    "positive": [
                        {"text": "foot focus", "role": "composition"},
                        {"text": "soles toward viewer", "role": "pose"},
                    ],
                    "negative": [
                        {"text": "face focus", "role": "composition"},
                    ],
                },
            }
        )

        bundle = ScriptComposer().compose_nodes(character=character, action=action)

        self.assertEqual(bundle.meta.shot.body_scope, "foot_detail")
        self.assertIn("akemi homura", bundle.prompt.positive)
        self.assertIn("bare soles", bundle.prompt.positive)
        self.assertIn("foot focus", bundle.prompt.positive)
        self.assertIn("soles toward viewer", bundle.prompt.positive)
        self.assertNotIn("purple eyes", bundle.prompt.positive)
        self.assertNotIn("black hair", bundle.prompt.positive)
        self.assertNotIn("school uniform", bundle.prompt.positive)
        self.assertIn("extra toes", bundle.prompt.negative)
        self.assertIn("face focus", bundle.prompt.negative)
        self.assertEqual(bundle.meta.character_ref, "homura")
        self.assertEqual(bundle.meta.action_ref, "foot_closeup")
        self.assertEqual(bundle.meta.constraints.forbidden_parts, ["purple eyes"])

    def test_compose_nodes_can_override_body_scope(self):
        character = NodeDocument.model_validate(
            {
                "kind": "character",
                "id": "homura",
                "prompt": {
                    "positive": [
                        {"text": "akemi homura", "include_scopes": ["*"]},
                        {"text": "purple eyes", "include_scopes": ["face_detail"]},
                        {"text": "bare soles", "include_scopes": ["foot_detail"]},
                    ],
                },
            }
        )

        bundle = ScriptComposer().compose_nodes(character=character, body_scope="face_detail")

        self.assertIn("purple eyes", bundle.prompt.positive)
        self.assertNotIn("bare soles", bundle.prompt.positive)


if __name__ == "__main__":
    unittest.main()
