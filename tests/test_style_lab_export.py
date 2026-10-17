import json
import tempfile
from pathlib import Path
from unittest import TestCase

from tags_machine_core.nodes.novelai_artist import NovelAIArtistRepository
from tags_machine_core.style_lab.artist_test import (
    ArtistTestSettings,
    matrix_cells,
    pick_regression_images,
    plan_seed,
    strip_style,
    style_blocks,
    style_norms,
    subject_norms,
)
from tags_machine_core.style_lab.export import (
    ArtistExporter,
    ExportError,
    ExportRequest,
    diff_artists,
    folder_name,
    free_folder,
    render_tags_txt,
    roundtrip_problems,
    suggest_author,
)
from tags_machine_core.style_lab.metadata import build_image_record
from tags_machine_core.style_lab.recipe import Recipe, RecipeToken, artist_node, line_text, tokens_from_text
from tags_machine_core.style_lab.workspace import WorkspaceInfo

from tests.test_style_lab import write_nai_png


def _values(prefix="", suffix="", negative="", params=None, flags=("not_quailty_prompts",)):
    return {
        "prompt_prefix": [prefix] if prefix else [],
        "prompt_suffix": [suffix] if suffix else [],
        "negative_prompt": [negative] if negative else [],
        "params": params or {},
        "flags": list(flags),
    }


def _recipe(**fields) -> Recipe:
    base = {
        "name": "测试",
        "stage": "edit",
        "locked": True,
        "prefix": tokens_from_text("artist:foo, 1.2::ink::"),
        "subject": tokens_from_text("1girl, solo, sitting"),
        "suffix": tokens_from_text("very aesthetic, masterpiece"),
        "negative": tokens_from_text("lowres, bad anatomy"),
        "model": "nai-diffusion-4-5-full",
        "params": {"sampler": "k_euler_ancestral", "steps": 28, "scale": 5.0},
        "use_source_vibe": False,
    }
    base.update(fields)
    return Recipe(**base)


class TagsTxtTest(TestCase):
    def test_layout_matches_legacy_format(self):
        text = render_tags_txt(
            _values("artist:foo, ink", "masterpiece", "lowres", {"model": "m", "steps": 28})
        )
        self.assertEqual(
            text.splitlines(),
            [
                "artist:foo, ink",
                ",",
                "masterpiece",
                "type, not_quailty_prompts",
                "=",
                "origin_uc, lowres",
                'gen_json, {"model":"m","steps":28}',
            ],
        )

    def test_roundtrip_through_official_reader(self):
        values = _values("artist:foo, 1.4::a, b::", "masterpiece, [x|y]", "lowres", {"steps": 28, "sm": False})
        self.assertEqual(roundtrip_problems(render_tags_txt(values), values), [])

    def test_empty_prefix_keeps_suffix_in_line_three(self):
        values = _values("", "masterpiece")
        text = render_tags_txt(values)
        self.assertTrue(text.startswith(",\n,\nmasterpiece\n"))
        self.assertEqual(roundtrip_problems(text, values), [])

    def test_roundtrip_detects_lines_the_reader_misparses(self):
        # 以 type 开头的行会被读取器当成标记行。
        values = _values("typewriter, artist:foo", "masterpiece")
        problems = roundtrip_problems(render_tags_txt(values), values)
        self.assertIn("前缀读回后和配方不一致", problems)
        self.assertIn("标记读回后和配方不一致", problems)

    def test_line_text_flattens_newlines(self):
        tokens = tokens_from_text("artist:foo\nink, 1.2::a,\nb::\nmasterpiece")
        self.assertEqual(line_text(tokens), "artist:foo, ink, 1.2::a, b::, masterpiece")


class NamingTest(TestCase):
    def test_folder_name_and_validation(self):
        self.assertEqual(folder_name("105845157", "Crisp_Manga_Ink"), "105845157_Crisp_Manga_Ink")
        self.assertEqual(folder_name(None, "Soft"), "Soft")
        for bad in ("Crisp Manga", "画风", "a__b", "_a", ""):
            with self.assertRaises(ExportError):
                folder_name("1", bad)
        with self.assertRaises(ExportError):
            folder_name("../x", "Soft")

    def test_free_folder_creates_sibling_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(free_folder(root, "1_Soft"), "1_Soft")
            (root / "1_Soft").mkdir()
            self.assertEqual(free_folder(root, "1_Soft"), "1_Soft_v2")
            (root / "1_Soft_v2").mkdir()
            self.assertEqual(free_folder(root, "1_Soft"), "1_Soft_v3")
            self.assertEqual(free_folder(root, "1_Soft_v2"), "1_Soft_v3")

    def test_suggest_author_from_corpus_folder(self):
        info = WorkspaceInfo(id="w", name="w", kind="folder", root="F:/artist_parse/20260717/105845157", data_dir="x")
        self.assertEqual(suggest_author(info), "105845157")
        info = info.model_copy(update={"root": "F:/图库/某画师"})
        self.assertIsNone(suggest_author(info))


class DiffTest(TestCase):
    def test_token_and_param_diff(self):
        before = _values("artist:foo, ink", "masterpiece", "lowres", {"steps": 28, "scale": 5.0})
        after = _values("artist:foo, Ink, artist:bar", "", "lowres", {"steps": 28, "scale": 6.0})
        diff = diff_artists(before, after)
        self.assertEqual(diff["prefix"]["added"], ["artist:bar"])
        self.assertEqual(diff["prefix"]["removed"], [])
        self.assertEqual(diff["suffix"]["removed"], ["masterpiece"])
        self.assertTrue(diff["negative"]["same"])
        self.assertEqual(diff["params"], [{"key": "scale", "before": 5.0, "after": 6.0}])
        self.assertIsNone(diff["flags"])

    def test_vibe_compared_by_count(self):
        before = _values(params={"reference_image_multiple": ["a"]})
        after = _values(params={"reference_image_multiple": ["a", "b"]})
        self.assertEqual(diff_artists(before, after)["params"], [{"key": "vibe", "before": 1, "after": 2}])


class ExporterTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.artist_root = self.tmp / "design" / "画风"
        self.exporter = ArtistExporter(self.artist_root)
        self.source = write_nai_png(self.tmp / "corpus" / "origin" / "2026-01-11_1_a" / "1_p0.png")
        self.record = build_image_record(self.source, base=self.tmp / "corpus" / "origin")
        self.info = WorkspaceInfo(id="w", name="w", kind="folder", root=str(self.tmp / "corpus"), data_dir=str(self.tmp / "data"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_export_writes_folder_that_loads_like_the_recipe(self):
        recipe = _recipe()
        request = ExportRequest(name="Ink_Test", author="1")
        preview = self.exporter.preview(recipe, request, record=self.record, exports=[])
        self.assertEqual(preview["folder"], "1_Ink_Test")
        self.assertTrue(preview["roundtrip_ok"], preview["problems"])
        self.assertIsNone(preview["compare"])
        entry = self.exporter.export(recipe, request, record=self.record, info=self.info, expected_folder="1_Ink_Test")
        folder = self.artist_root / "1_Ink_Test"
        self.assertEqual(Path(entry["path"]), folder)
        self.assertEqual((folder / "tags.txt").read_text(encoding="utf-8"), preview["tags_txt"])
        self.assertIn("source_1_p0.png", entry["files"])
        self.assertEqual((folder / "source_action_1_p0.txt").read_text(encoding="utf-8"), "1girl, solo, sitting")
        marker = json.loads((folder / "stylelab_export.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["recipe"]["id"], recipe.id)

        loaded = NovelAIArtistRepository(self.artist_root.parent).load("1_Ink_Test").artist_payload()
        expected = artist_node(recipe, source_path=self.record.path)["renderers"]["novelai"]
        self.assertEqual(loaded["prompt_prefix"], expected["prompt_prefix"])
        self.assertEqual(loaded["prompt_suffix"], expected["prompt_suffix"])
        self.assertEqual([loaded["negative_prompt"]], expected["negative_prompt"])
        self.assertEqual(loaded["params"], expected["params"])
        self.assertNotIn("width", loaded["params"])

        # 再导出一次：不覆盖，建并列版本，默认和上一次导出对比。
        exports = [entry]
        second = self.exporter.preview(recipe, request, record=self.record, exports=exports)
        self.assertEqual(second["folder"], "1_Ink_Test_v2")
        self.assertTrue(second["exists"])
        self.assertEqual(second["compare"]["ref"], "1_Ink_Test")
        self.assertTrue(second["compare"]["diff"]["style"]["same"])

    def test_export_refuses_when_target_moved_since_preview(self):
        from tags_machine_core.style_lab.export import ExportConflictError

        (self.artist_root / "1_Ink_Test").mkdir(parents=True)
        with self.assertRaises(ExportConflictError):
            self.exporter.export(
                _recipe(), ExportRequest(name="Ink_Test", author="1"), record=self.record, info=self.info, expected_folder="1_Ink_Test"
            )
        self.assertEqual(sorted(path.name for path in self.artist_root.iterdir()), ["1_Ink_Test"])

    def test_default_compare_picks_closest_author_artist(self):
        for name, prefix in (("1_Other", "artist:zzz"), ("1_Close", "artist:foo, 1.2::ink::")):
            folder = self.artist_root / name
            folder.mkdir(parents=True)
            (folder / "tags.txt").write_text(f"{prefix}\n,\n", encoding="utf-8")
        preview = self.exporter.preview(_recipe(), ExportRequest(name="New", author="1"), record=self.record, exports=[])
        self.assertEqual(preview["candidates"], ["1_Close", "1_Other"])
        self.assertEqual(preview["compare"]["ref"], "1_Close")
        self.assertEqual(preview["compare"]["diff"]["style"]["added"], ["very aesthetic", "masterpiece"])


class ArtistTestPlanTest(TestCase):
    def test_strip_style_removes_recipe_style_and_style_categories(self):
        recipe = _recipe(dropped=[RecipeToken(text="watermark")])
        subject, removed = strip_style(
            "artist:foo, artist:new_guy, 1girl, Very_Aesthetic, sitting, watermark, year 2024",
            style_norms(recipe),
            {"year 2024": "meta", "1girl": "count"},
        )
        self.assertEqual(subject, "1girl, sitting")
        self.assertEqual(removed, ["artist:foo", "artist:new_guy", "Very_Aesthetic", "watermark", "year 2024"])

    def test_strip_style_keeps_tokens_the_recipe_left_in_subject(self):
        recipe = _recipe(subject=tokens_from_text("1girl, outer glow"))
        categories = {"outer glow": "style", "drop shadow": "style"}
        subject, removed = strip_style(
            "1girl, outer glow, drop shadow", style_norms(recipe), categories, subject_norms(recipe)
        )
        self.assertEqual(subject, "1girl, outer glow")
        self.assertEqual(removed, ["drop shadow"])

    def test_strip_style_cuts_whole_blocks_and_keeps_dropped_by_default(self):
        prefix = "0.6::ixy::, 1.2::oekaki,:: -2::sketch, jaggy lines,::, 1.5::key art:: highres"
        recipe = _recipe(
            prefix=[RecipeToken(text=prefix)],
            subject=[RecipeToken(text="1girl, sex", origins=["action:x"])],
            suffix=[RecipeToken(text="very aesthetic, masterpiece")],
            dropped=[RecipeToken(text="0.5::Glitch::, abstract, orange black white palette, poster")],
        )
        prompt = f"{prefix}, 0.5::Glitch::, abstract, orange black white palette,  poster, very aesthetic, masterpiece"
        categories = {"abstract": "style", "orange black white palette": "style"}
        # 默认：丢弃的词留在内容里，分类说是风格也不去掉；画风块整段去掉，不留 "::" 碎片。
        subject, removed = strip_style(
            prompt, style_norms(recipe, strip_dropped=False), categories,
            subject_norms(recipe, keep_dropped=True), blocks=style_blocks(recipe, strip_dropped=False),
        )
        self.assertEqual(subject, "0.5::Glitch::, abstract, orange black white palette,  poster")
        self.assertEqual(removed, [prefix, "very aesthetic, masterpiece"])
        # 一起去掉：只剩空。
        subject, _ = strip_style(prompt, style_norms(recipe), categories, subject_norms(recipe), blocks=style_blocks(recipe))
        self.assertEqual(subject, "")

    def test_strip_style_block_cut_respects_tag_boundaries(self):
        subject, removed = strip_style("1girl, girl, sitting", set(), {}, blocks=["girl"])
        self.assertEqual(subject, "1girl, sitting")
        self.assertEqual(removed, ["girl"])
        # 两个权重组之间只隔空格时是一个 tag，整个去掉，不会留下半个组或空的 "::"。
        weighted = "1.2::oekaki,:: -2::sketch, jaggy lines,::"
        self.assertEqual(strip_style(f"{weighted}, 1girl", {weighted}, {}), ("1girl", [weighted]))
        self.assertEqual(strip_style(f"{weighted}, 1girl", set(), {}, blocks=[weighted]), ("1girl", [weighted]))

    def test_pick_regression_images_one_per_post_source_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [
                write_nai_png(root / "2026-01-01_10_a" / "10_p0.png"),
                write_nai_png(root / "2026-01-01_10_a" / "10_p1.png"),
                write_nai_png(root / "2026-02-01_11_b" / "11_p0.png"),
                write_nai_png(root / "2026-03-01_12_c" / "12_p0.png", request_type="NativeInfillingRequest"),
                write_nai_png(root / "2025-12-01_13_d" / "13_p0.png"),
            ]
            records = [build_image_record(path, base=root) for path in paths]
            picked = pick_regression_images(records, None, first_id=records[4].id, limit=3)
            self.assertEqual([image.post.post_id for image in picked], ["13", "11", "10"])
            only = pick_regression_images(records, [records[0].id, records[1].id], first_id=None, limit=4)
            self.assertEqual(len(only), 1)

    def test_seed_plan_and_matrix_cells(self):
        settings = ArtistTestSettings(kind="regression", artist="a")
        self.assertEqual(plan_seed(settings, 99, 5), 99)
        self.assertEqual(plan_seed(settings, None, 5), 5)
        fixed = ArtistTestSettings(kind="regression", artist="a", seed_mode="fixed", seed=7)
        self.assertEqual(plan_seed(fixed, 99, 5), 7)
        matrix = ArtistTestSettings(kind="matrix", artist="a", characters=["c1", "c2"], actions=["a1"])
        self.assertEqual(matrix_cells(matrix), [("c1", "a1"), ("c2", "a1")])
        with self.assertRaises(ValueError):
            ArtistTestSettings(kind="matrix", artist="a")

    def test_size_mode_defaults_follow_old_settings(self):
        self.assertEqual(ArtistTestSettings(kind="regression", artist="a").size_mode, "source")
        old = ArtistTestSettings(kind="matrix", artist="a", actions=["x"], width=832, height=1216)
        self.assertEqual(old.size_mode, "custom")
        self.assertEqual(ArtistTestSettings(kind="regression", artist="a", size_mode="loop").dropped, "keep")
        with self.assertRaises(ValueError):
            ArtistTestSettings(kind="regression", artist="a", size_mode="custom")


class DiffNoiseTest(TestCase):
    def test_runtime_size_and_empty_values_are_not_differences(self):
        before = _values(params={"width": 832, "height": 1216, "reference_strength_multiple": [], "reference_image_multiple": []})
        after = _values(params={})
        self.assertEqual(diff_artists(before, after)["params"], [])
