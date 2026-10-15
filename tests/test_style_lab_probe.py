from unittest import TestCase

from pydantic import ValidationError

from tags_machine_core.style_lab.probe import ProbeSettings, ablate, probe_variants, swap_character, SwapCharacter
from tags_machine_core.style_lab.recipe import (
    Recipe,
    RecipeCaption,
    RecipeCharacter,
    block_from_text,
    tokens_from_text,
    tokens_text,
)


CATEGORIES = {
    "1girl": "count",
    "solo": "count",
    "akemi homura": "character",
    "black hair": "appearance",
    "school uniform": "clothing",
    "sitting": "action",
    "tall": "appearance",
}
MIKU = SwapCharacter(ref="chars/miku", name="Miku", tags=["hatsune miku", "aqua hair"])


def make_recipe(subject: str, captions: list[str] | None = None) -> Recipe:
    return Recipe(
        name="r",
        prefix=tokens_from_text("artist:foo, flat color"),
        subject=tokens_from_text(subject),
        suffix=tokens_from_text("very aesthetic"),
        character=RecipeCharacter(
            enabled=bool(captions),
            captions=[RecipeCaption(tokens=tokens_from_text(text)) for text in captions or []],
        ),
    )


class SwapTest(TestCase):
    def test_swap_into_subject_replaces_identity_where_it_was(self):
        recipe = make_recipe("1girl, solo, akemi homura, black hair, school uniform, sitting")
        settings = ProbeSettings(kind="swap", characters=[MIKU])
        variant, meta = swap_character(recipe, MIKU, CATEGORIES, settings)
        self.assertEqual(tokens_text(variant.subject), "1girl, solo, hatsune miku, aqua hair, sitting")
        self.assertEqual(meta["removed"], ["akemi homura", "black hair", "school uniform"])
        self.assertEqual(meta["target"], "主体")
        self.assertEqual(variant.subject[2].origins, ["character:chars/miku"])
        # 画风不动，原配方也不动。
        self.assertEqual(variant.prefix, recipe.prefix)
        self.assertEqual(tokens_text(recipe.subject), "1girl, solo, akemi homura, black hair, school uniform, sitting")

        keep_clothes = ProbeSettings(kind="swap", characters=[MIKU], replace_clothing=False)
        variant, _ = swap_character(recipe, MIKU, CATEGORIES, keep_clothes)
        self.assertIn("school uniform", tokens_text(variant.subject))

    def test_swap_without_identity_goes_after_the_count(self):
        recipe = make_recipe("1girl, solo, sitting")
        variant, meta = swap_character(recipe, MIKU, CATEGORIES, ProbeSettings(kind="swap", characters=[MIKU]))
        self.assertEqual(tokens_text(variant.subject), "1girl, solo, hatsune miku, aqua hair, sitting")
        self.assertEqual(meta["removed"], [])

    def test_swap_into_the_first_character_caption(self):
        recipe = make_recipe(
            "1girl, 1boy, akemi homura, black hair, sitting", ["girl, akemi homura, black hair, sitting", "boy, tall"]
        )
        variant, meta = swap_character(recipe, MIKU, CATEGORIES, ProbeSettings(kind="swap", characters=[MIKU]))
        captions = variant.character.captions
        # 角色提示词里的动作（比如动作卡加进去的）留着，只换角色本身。
        self.assertEqual(tokens_text(captions[0].tokens), "girl, hatsune miku, aqua hair, sitting")
        self.assertEqual(meta["removed"], ["akemi homura", "akemi homura", "black hair"])
        self.assertEqual(tokens_text(captions[1].tokens), "boy, tall")
        # 主体里只去掉角色名，外貌可能是别的角色的。
        self.assertEqual(tokens_text(variant.subject), "1girl, 1boy, black hair, sitting")
        self.assertEqual(meta["target"], "角色提示词 #1")

        second = ProbeSettings(kind="swap", characters=[MIKU], caption_index=1)
        variant, meta = swap_character(recipe, MIKU, CATEGORIES, second)
        self.assertEqual(tokens_text(variant.character.captions[1].tokens), "boy, hatsune miku, aqua hair")
        self.assertEqual(meta["target"], "角色提示词 #2")


    def test_swap_inside_whole_blocks(self):
        # 配方里主体、角色提示词都是整组的一块：按 tag 判断去留，其余文字不变。
        recipe = make_recipe("", None).model_copy(
            update={
                "subject": block_from_text("1girl, 1boy, akemi homura, sitting"),
                "character": RecipeCharacter(
                    enabled=True,
                    captions=[RecipeCaption(tokens=block_from_text("girl, akemi homura, black hair|sitting"))],
                ),
            }
        )
        variant, meta = swap_character(recipe, MIKU, CATEGORIES, ProbeSettings(kind="swap", characters=[MIKU]))
        self.assertEqual(meta["target"], "角色提示词 #1")
        self.assertEqual(tokens_text(variant.character.captions[0].tokens), "girl, hatsune miku, aqua hair|sitting")
        self.assertEqual(tokens_text(variant.subject), "1girl, 1boy, sitting")

    def test_swap_follows_the_character_into_the_subject(self):
        # 角色在主体，角色提示词里只写了动作：换主体，动作照留。
        recipe = make_recipe("1girl, akemi homura, black hair, sitting", ["girl, sitting, school uniform"])
        variant, meta = swap_character(recipe, MIKU, CATEGORIES, ProbeSettings(kind="swap", characters=[MIKU]))
        self.assertEqual(meta["target"], "主体")
        self.assertEqual(tokens_text(variant.subject), "1girl, hatsune miku, aqua hair, sitting")
        # 只有一条角色提示词时它写的就是这个角色：服装一起换掉，动作留着。
        self.assertEqual(tokens_text(variant.character.captions[0].tokens), "girl, sitting")
        self.assertEqual(meta["removed"], ["akemi homura", "black hair", "school uniform"])

    def test_swap_without_names_goes_where_the_looks_are(self):
        recipe = make_recipe("1girl, 1boy, sitting", ["boy, sitting", "girl, black hair"])
        variant, meta = swap_character(recipe, MIKU, CATEGORIES, ProbeSettings(kind="swap", characters=[MIKU]))
        self.assertEqual(meta["target"], "角色提示词 #2")
        self.assertEqual(tokens_text(variant.character.captions[1].tokens), "girl, hatsune miku, aqua hair")

    def test_swap_into_the_subject_on_request(self):
        recipe = make_recipe("1girl, sitting", ["girl, akemi homura", "boy, tall"])
        settings = ProbeSettings(kind="swap", characters=[MIKU], target="subject")
        variant, meta = swap_character(recipe, MIKU, CATEGORIES, settings)
        self.assertEqual(meta["target"], "主体")
        self.assertEqual(tokens_text(variant.subject), "1girl, hatsune miku, aqua hair, sitting")
        # 两条以上的角色提示词不知道是谁的，不动。
        self.assertEqual([tokens_text(c.tokens) for c in variant.character.captions], ["girl, akemi homura", "boy, tall"])


class AblationTest(TestCase):
    def test_ablate_removes_only_the_chosen_style_tokens(self):
        recipe = make_recipe("1girl")
        unit = {"label": "flat color", "token_ids": [recipe.prefix[1].id]}
        settings = ProbeSettings(kind="ablation", units=[unit], include_baseline=False)
        self.assertTrue(settings.include_baseline)
        variants = probe_variants(recipe, settings, {})
        self.assertEqual([meta["role"] for _, meta in variants], ["baseline", "variant"])
        variant, meta = variants[1]
        self.assertEqual(tokens_text(variant.prefix), "artist:foo")
        self.assertEqual(tokens_text(variant.suffix), "very aesthetic")
        self.assertEqual(meta["removed"], ["flat color"])

        both = settings.units[0].model_copy(update={"token_ids": [recipe.prefix[0].id, recipe.suffix[0].id]})
        variant, meta = ablate(recipe, both)
        self.assertEqual((tokens_text(variant.prefix), variant.suffix), ("flat color", []))

        stale = both.model_copy(update={"token_ids": [recipe.subject[0].id]})
        with self.assertRaises(ValueError):
            ablate(recipe, stale)

    def test_settings_validation(self):
        with self.assertRaises(ValidationError):
            ProbeSettings(kind="swap")
        with self.assertRaises(ValidationError):
            ProbeSettings(kind="ablation")
        with self.assertRaises(ValidationError):
            ProbeSettings(kind="swap", characters=[MIKU], seed_mode="fixed")
