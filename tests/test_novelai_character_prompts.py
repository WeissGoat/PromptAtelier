import unittest

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.clients import NovelAIClient
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
        self.assertEqual(
            request.params["characterPrompts"],
            [
                {
                    "prompt": "girl, akemi homura, black hair",
                    "uc": "",
                    "center": {"x": 0.5, "y": 0.5},
                    "enabled": True,
                },
                {
                    "prompt": "girl, kaname madoka, pink hair",
                    "uc": "",
                    "center": {"x": 0.5, "y": 0.5},
                    "enabled": True,
                },
            ],
        )
        negative_caption = request.params["v4_negative_prompt"]["caption"]
        self.assertEqual(
            negative_caption["char_captions"],
            [
                {"char_caption": "", "centers": [{"x": 0.5, "y": 0.5}]},
                {"char_caption": "", "centers": [{"x": 0.5, "y": 0.5}]},
            ],
        )

    def test_shared_character_tags_are_copied_to_each_matching_character_prompt(self):
        homura = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"], "clothes": ["white dress"]},
        )
        madoka = NodeDocument(
            kind="character",
            id="madoka",
            tags={"character": ["kaname madoka"], "clothes": ["white dress"]},
        )
        resolved = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=homura),
                ResolvedNode(role="character", ref="madoka", index=1, node=madoka),
            ]
        )
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, kaname madoka, 2girls, white dress, standing side by side",
        )

        request = NovelAIRenderAdapter().build_request(
            bundle,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        caption = request.params["v4_prompt"]["caption"]
        char_captions = [item["char_caption"] for item in caption["char_captions"]]
        self.assertEqual(
            char_captions,
            [
                "girl, akemi homura, white dress",
                "girl, kaname madoka, white dress",
            ],
        )
        self.assertEqual(caption["base_caption"], "2girls, standing side by side")
        self.assertNotIn("white dress", caption["base_caption"])

    def test_male_prompt_adds_extra_boy_character_caption_by_default(self):
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
        resolved = ResolvedNodeSet(
            [
                ResolvedNode(role="character", ref="homura", index=0, node=homura),
                ResolvedNode(role="character", ref="madoka", index=1, node=madoka),
            ]
        )
        bundle = ScriptComposer().compose_full_prompt(
            prompt=(
                "akemi homura, kaname madoka, black hair, pink hair, "
                "2girls, 1boy, threesome"
            ),
        )

        request = NovelAIRenderAdapter().build_request(
            bundle,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        positive_caption = request.params["v4_prompt"]["caption"]
        negative_caption = request.params["v4_negative_prompt"]["caption"]
        self.assertEqual(
            [item["char_caption"] for item in positive_caption["char_captions"]],
            [
                "girl, akemi homura, black hair",
                "girl, kaname madoka, pink hair",
                "boy, ",
            ],
        )
        self.assertEqual(positive_caption["base_caption"], "2girls, 1boy, threesome")
        self.assertEqual(len(negative_caption["char_captions"]), 3)
        self.assertEqual(negative_caption["char_captions"][2]["char_caption"], "")
        self.assertEqual(
            request.params["characterPrompts"][2],
            {
                "prompt": "boy, ",
                "uc": "",
                "center": {"x": 0.5, "y": 0.5},
                "enabled": True,
            },
        )
        self.assertTrue(request.meta["character_prompts"]["male_caption_added"])

    def test_male_caption_is_in_novelai_payload_parameters(self):
        homura = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"]},
        )
        resolved = ResolvedNodeSet(
            [ResolvedNode(role="character", ref="homura", index=0, node=homura)]
        )
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, 1boy, group scene",
        )
        request = NovelAIRenderAdapter().build_request(
            bundle,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        payload = NovelAIClient(access_token="token", retry=1).build_payload(request)
        parameters = payload["parameters"]

        self.assertEqual(
            parameters["v4_prompt"]["caption"]["char_captions"],
            [
                {
                    "char_caption": "girl, akemi homura",
                    "centers": [{"x": 0.5, "y": 0.5}],
                },
                {"char_caption": "boy, ", "centers": [{"x": 0.5, "y": 0.5}]},
            ],
        )
        self.assertEqual(
            parameters["v4_negative_prompt"]["caption"]["char_captions"],
            [
                {"char_caption": "", "centers": [{"x": 0.5, "y": 0.5}]},
                {"char_caption": "", "centers": [{"x": 0.5, "y": 0.5}]},
            ],
        )
        self.assertEqual(
            parameters["characterPrompts"],
            [
                {
                    "prompt": "girl, akemi homura",
                    "uc": "",
                    "center": {"x": 0.5, "y": 0.5},
                    "enabled": True,
                },
                {
                    "prompt": "boy, ",
                    "uc": "",
                    "center": {"x": 0.5, "y": 0.5},
                    "enabled": True,
                },
            ],
        )
        self.assertNotIn("_character_prompt_meta", parameters)

    def test_male_caption_can_be_disabled(self):
        homura = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"]},
        )
        resolved = ResolvedNodeSet(
            [ResolvedNode(role="character", ref="homura", index=0, node=homura)]
        )
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, 1boy, standing",
        )

        request = NovelAIRenderAdapter().build_request(
            bundle,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto", "add_male_caption": False}},
            resolved_nodes=resolved,
        )

        caption = request.params["v4_prompt"]["caption"]
        self.assertEqual(
            [item["char_caption"] for item in caption["char_captions"]],
            ["girl, akemi homura"],
        )
        self.assertEqual(caption["base_caption"], "1boy, standing")
        self.assertFalse(request.meta["character_prompts"]["male_caption_added"])

    def test_penis_and_erection_do_not_add_male_caption_without_male_subject(self):
        homura = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"]},
        )
        resolved = ResolvedNodeSet(
            [ResolvedNode(role="character", ref="homura", index=0, node=homura)]
        )
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, penis, erection, interactive pose",
        )

        request = NovelAIRenderAdapter().build_request(
            bundle,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        caption = request.params["v4_prompt"]["caption"]
        self.assertEqual(
            [item["char_caption"] for item in caption["char_captions"]],
            ["girl, akemi homura"],
        )
        self.assertEqual(caption["base_caption"], "penis, erection, interactive pose")
        self.assertFalse(request.meta["character_prompts"]["male_caption_added"])

    def test_existing_male_character_caption_is_not_duplicated(self):
        male = NodeDocument(
            kind="character",
            id="male_extra",
            tags={"character": ["boy"]},
        )
        resolved = ResolvedNodeSet(
            [ResolvedNode(role="character", ref="male_extra", index=0, node=male)]
        )
        bundle = ScriptComposer().compose_full_prompt(prompt="boy, 1boy, standing")

        request = NovelAIRenderAdapter().build_request(
            bundle,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto", "default_caption_prefix": ""}},
            resolved_nodes=resolved,
        )

        caption = request.params["v4_prompt"]["caption"]
        self.assertEqual(
            [item["char_caption"] for item in caption["char_captions"]],
            ["boy"],
        )
        self.assertEqual(caption["base_caption"], "1boy, standing")
        self.assertFalse(request.meta["character_prompts"]["male_caption_added"])

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
        artist = NodeDocument(
            kind="artist",
            id="legacy_artist",
            renderers={
                "novelai": {
                    "legacy_compat": True,
                    "model": "nai-diffusion-4-5-full",
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
        )

        request = NovelAIRenderAdapter().build_request(
            bundle,
            artist=artist,
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
