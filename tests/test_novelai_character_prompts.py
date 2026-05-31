import unittest

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet
from tags_machine_core.renderers import NovelAIRenderAdapter


class NovelAICharacterPromptsTest(unittest.TestCase):
    def test_v45_auto_character_prompts_move_character_tags_to_char_captions(self):
        homura = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"], "hair": ["black hair"]},
        )
        madoka = NodeDocument(
            kind="character",
            id="madoka",
            tags={"character": ["kaname madoka"], "hair": ["pink hair"]},
        )
        action = NodeDocument(
            kind="action",
            id="duo",
            tags={"action": ["2girls, standing side by side"]},
        )
        resolved = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=homura),
                ResolvedNode(role="character", ref="madoka", index=1, node=madoka),
                ResolvedNode(role="action", ref="duo", index=0, node=action),
            ]
        )
        bundle = ScriptComposer().compose_resolved_nodes(resolved)

        request = NovelAIRenderAdapter().build_request(
            bundle,
            seed=123,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        caption = request.params["v4_prompt"]["caption"]
        self.assertEqual(caption["base_caption"], "2girls, standing side by side")
        self.assertEqual(
            caption["char_captions"],
            [
                {
                    "char_caption": "girl, akemi homura, black hair",
                    "centers": [{"x": 0.5, "y": 0.5}],
                },
                {
                    "char_caption": "girl, kaname madoka, pink hair",
                    "centers": [{"x": 0.5, "y": 0.5}],
                },
            ],
        )
        self.assertEqual(request.prompt, "2girls, standing side by side")
        self.assertEqual(request.meta["character_prompts"]["mode"], "auto")

    def test_character_prompts_stay_disabled_without_explicit_mode(self):
        character = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"]},
        )
        resolved = ResolvedNodeSet(
            [ResolvedNode(role="character", ref="homura", index=0, node=character)]
        )
        bundle = ScriptComposer().compose_resolved_nodes(resolved)

        request = NovelAIRenderAdapter().build_request(
            bundle,
            model="nai-diffusion-4-5-full",
            resolved_nodes=resolved,
        )

        self.assertEqual(request.params["v4_prompt"]["caption"]["char_captions"], [])
        self.assertIn("akemi homura", request.prompt)

    def test_full_prompt_character_prompts_respect_action_scope(self):
        character = NodeDocument(
            kind="character",
            id="homura",
            tags={
                "character": ["akemi homura"],
                "hair": ["black hair"],
                "eyes": ["purple eyes"],
                "feet": ["bare soles"],
            },
        )
        action = NodeDocument(
            kind="action",
            id="foot_closeup",
            tags={"action": ["foot focus"]},
            character_scope="foot_detail",
        )
        resolved = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=character),
                ResolvedNode(role="action", ref="foot_closeup", index=0, node=action),
            ]
        )
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, bare soles, foot focus",
        )

        request = NovelAIRenderAdapter().build_request(
            bundle,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        char_caption = request.params["v4_prompt"]["caption"]["char_captions"][0][
            "char_caption"
        ]
        self.assertIn("akemi homura", char_caption)
        self.assertIn("bare soles", char_caption)
        self.assertNotIn("black hair", char_caption)
        self.assertNotIn("purple eyes", char_caption)

    def test_character_prompts_apply_after_legacy_style_prompt_composition(self):
        character = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"], "feet": ["bare soles"]},
        )
        action = NodeDocument(
            kind="action",
            id="foot_closeup",
            tags={"action": ["foot focus"]},
            character_scope="foot_detail",
        )
        style = NodeDocument(
            kind="style",
            id="legacy_artist",
            renderers={
                "novelai": {
                    "legacy_compat": True,
                    "prompt_suffix": ["artist style"],
                }
            },
        )
        resolved = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=character),
                ResolvedNode(role="action", ref="foot_closeup", index=0, node=action),
            ]
        )
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, bare soles, foot focus",
            style_ref="legacy_artist",
        )

        request = NovelAIRenderAdapter().build_request(
            bundle,
            style=style,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        caption = request.params["v4_prompt"]["caption"]
        self.assertEqual(
            caption["char_captions"][0]["char_caption"],
            "girl, akemi homura, bare soles",
        )
        self.assertNotIn("akemi homura", caption["base_caption"])
        self.assertIn("foot focus", caption["base_caption"])
        self.assertIn("artist style", caption["base_caption"])
        self.assertIn("very aesthetic", caption["base_caption"])


if __name__ == "__main__":
    unittest.main()
