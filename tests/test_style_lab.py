import json
import random
import tempfile
import time
from pathlib import Path
from unittest import TestCase

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from tags_machine_core.style_lab import (
    RegenSettings,
    StyleLabService,
    WorkspaceStore,
    build_image_record,
    build_regen_request,
    compare_with_source,
    expected_diff_keys,
    image_similarity,
    parse_post_dir,
    plan_seeds,
)


def write_nai_png(
    path: Path, *, color="white", size=(64, 96), source="NovelAI Diffusion V4.5 4BDE2A90", **params
) -> Path:
    comment = {
        "prompt": "artist:foo, 1girl, solo, sitting",
        "uc": "lowres",
        "seed": 1234,
        "steps": 28,
        "scale": 5.0,
        "cfg_rescale": 0.0,
        "sampler": "k_euler_ancestral",
        "noise_schedule": "karras",
        "width": size[0],
        "height": size[1],
        "request_type": "PromptGenerateRequest",
        "v4_prompt": {
            "caption": {
                "base_caption": "artist:foo, 1girl, solo, sitting",
                "char_captions": [{"char_caption": "girl, silver hair", "centers": [{"x": 0.5, "y": 0.5}]}],
            },
            "use_coords": False,
            "use_order": True,
        },
        "v4_negative_prompt": {
            "caption": {"base_caption": "lowres", "char_captions": [{"char_caption": "bad hands", "centers": []}]}
        },
        "reference_strength_multiple": [],
        "signed_hash": "abc",
    }
    comment.update(params)
    info = PngInfo()
    info.add_text("Comment", json.dumps(comment))
    info.add_text("Source", source)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG", pnginfo=info)
    return path


class MetadataTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_reads_v4_captions_model_and_post(self):
        path = write_nai_png(self.tmp / "2026-01-11_139775078_ルサルカ" / "139775078_p0.png")
        record = build_image_record(path, base=self.tmp)
        self.assertTrue(record.has_metadata)
        self.assertEqual(record.model, "nai-diffusion-4-5-full")
        self.assertEqual(record.prompt, "artist:foo, 1girl, solo, sitting")
        self.assertEqual(record.negative_prompt, "lowres")
        self.assertEqual(len(record.char_captions), 1)
        self.assertEqual(record.char_captions[0].positive, "girl, silver hair")
        self.assertEqual(record.char_captions[0].negative, "bad hands")
        self.assertEqual((record.width, record.height, record.seed), (64, 96, 1234))
        self.assertEqual(record.post.post_id, "139775078")
        self.assertEqual(record.post.date, "2026-01-11")
        self.assertEqual(record.flags, [])

    def test_record_tells_curated_from_full_by_source_hash(self):
        def record(name, source, **params):
            return build_image_record(write_nai_png(self.tmp / name, source=source, **params), base=self.tmp)

        curated = record("a.png", "NovelAI Diffusion V5 DB276663")
        self.assertEqual(curated.model, "nai-diffusion-5-curated")
        self.assertNotIn("model_unverified", curated.flags)
        self.assertEqual(record("b.png", "NovelAI Diffusion V4.5 C02D4F98").model, "nai-diffusion-4-5-curated")
        # Source 比第三方客户端在 Comment 里另记的 model 可靠。
        self.assertEqual(record("c.png", "NovelAI Diffusion V5 DB276663", model="nai-diffusion-5-full").model, "nai-diffusion-5-curated")

        # 旧版本的哈希、Full Medium 也按官网的表认。
        self.assertEqual(record("e.png", "NovelAI Diffusion V5 657484A5").model, "nai-diffusion-5-full")
        self.assertEqual(record("f.png", "NovelAI Diffusion V5 93F4BD30").model, "nai-diffusion-5-full-medium")
        self.assertEqual(record("g.png", "NovelAI Diffusion V4 7ABFFA2A").model, "nai-diffusion-4-curated-preview")

        # 没登记的哈希按官网兜底：V5 当 Curated，并提醒核对。
        unknown = record("d.png", "NovelAI Diffusion V5 26E45D15")
        self.assertEqual(unknown.model, "nai-diffusion-5-curated")
        self.assertIn("model_unverified", unknown.flags)
        self.assertEqual(record("h.png", "NovelAI Diffusion V4.5 00000000").model, "nai-diffusion-4-5-curated")
        self.assertEqual(record("i.png", "NovelAI Diffusion V4 00000000").model, "nai-diffusion-4-curated-preview")

    def test_flags_vibe_missing_inpaint_and_no_metadata(self):
        vibe_missing = write_nai_png(self.tmp / "a.png", reference_strength_multiple=[0.6])
        self.assertIn("vibe_missing", build_image_record(vibe_missing, base=self.tmp).flags)

        with_vibe = write_nai_png(
            self.tmp / "b.png",
            reference_image_multiple=["AAAA"],
            reference_strength_multiple=[0.6],
            reference_information_extracted_multiple=[1.0],
        )
        record = build_image_record(with_vibe, base=self.tmp)
        self.assertEqual(record.vibe.count, 1)
        self.assertEqual(len(record.vibe.hashes[0]), 8)
        self.assertNotIn("vibe_missing", record.flags)

        inpaint = write_nai_png(self.tmp / "c.png", request_type="NativeInfillingRequest")
        self.assertIn("inpaint", build_image_record(inpaint, base=self.tmp).flags)

        plain = self.tmp / "d.png"
        Image.new("RGB", (8, 8)).save(plain)
        record = build_image_record(plain, base=self.tmp)
        self.assertEqual(record.flags, ["no_metadata"])
        self.assertFalse(record.has_metadata)

    def test_parse_post_dir_without_pattern(self):
        self.assertIsNone(parse_post_dir("misc").post_id)


class WorkspaceStoreTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.store = WorkspaceStore(self.tmp / "runtime")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_folder_workspace_scans_origin_only_and_reuses_records(self):
        author = self.tmp / "20260717" / "105845157"
        write_nai_png(author / "origin" / "2026-01-11_1_a" / "1_p0.png")
        write_nai_png(author / "origin" / "2026-01-12_2_b" / "2_p0.png")
        write_nai_png(author / "group" / "copy.png")

        info = self.store.open_folder(author)
        self.assertEqual(info.name, "105845157 · 20260717")
        self.assertTrue((author / ".stylelab" / "workspace.json").is_file())
        index, stats = self.store.scan(info)
        self.assertEqual([r.rel_path for r in index.images], ["origin/2026-01-11_1_a/1_p0.png", "origin/2026-01-12_2_b/2_p0.png"])
        self.assertEqual(stats["read"], 2)

        _, stats = self.store.scan(info)
        self.assertEqual((stats["read"], stats["reused"]), (0, 2))
        self.assertFalse(self.store.needs_rescan(info))

        # 解析规则升级后，文件没变的旧记录也要重新读。
        index = self.store.load_index(info)
        index.images[0].record_version = 0
        (Path(info.data_dir) / "index.json").write_text(index.model_dump_json(by_alias=True), encoding="utf-8")
        self.store._index_cache.pop(info.id, None)
        self.assertTrue(self.store.needs_rescan(info))
        _, stats = self.store.scan(info)
        self.assertEqual((stats["read"], stats["reused"]), (1, 1))

        # 重开同一个文件夹得到同一个工作区。
        self.assertEqual(self.store.open_folder(author).id, info.id)
        self.assertEqual([item.id for item in self.store.list_workspaces()], [info.id])

    def test_files_workspace_and_allowed_files(self):
        a = write_nai_png(self.tmp / "x" / "a.png")
        info = self.store.open_files([str(a)])
        index, _ = self.store.scan(info)
        self.assertEqual(len(index.images), 1)
        self.assertTrue(self.store.is_allowed_file(info, Path(index.images[0].path)))
        self.assertFalse(self.store.is_allowed_file(info, self.tmp / "other.png"))
        _, run_dir = self.store.new_run_dir(info)
        self.assertTrue(self.store.is_allowed_file(info, run_dir / "out.png"))


class RegenerateTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.record = build_image_record(write_nai_png(self.tmp / "s.png"), base=self.tmp)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_plan_seeds(self):
        self.assertEqual(plan_seeds(RegenSettings(count=3), 10), [10, 11, 12])
        self.assertEqual(plan_seeds(RegenSettings(count=2, seed_mode="fixed", seed=5), 10), [5, 6])
        seeds = plan_seeds(RegenSettings(count=2, seed_mode="random"), 10, rng=random.Random(1))
        self.assertEqual(len(seeds), 2)
        with self.assertRaises(ValueError):
            RegenSettings(seed_mode="fixed")
        with self.assertRaises(ValueError):
            RegenSettings(overrides={"prompt": "x"})

    def test_build_request_keeps_source_params_and_applies_overrides(self):
        settings = RegenSettings(size_mode="custom", width=832, height=1216, overrides={"steps": 23, "model": ""})
        request = build_regen_request(self.record, settings, 99)
        self.assertEqual(request["model"], "nai-diffusion-4-5-full")
        self.assertEqual(request["seed"], 99)
        self.assertEqual(request["size"], {"width": 832, "height": 1216})
        self.assertEqual(request["params"]["steps"], 23)
        self.assertEqual(request["params"]["seed"], 99)
        self.assertEqual(
            request["params"]["v4_prompt"]["caption"]["char_captions"][0]["char_caption"], "girl, silver hair"
        )
        self.assertEqual(request["meta"]["source_image_path"], self.record.path)
        self.assertEqual(expected_diff_keys(settings, self.record), {"steps", "width", "height"})
        self.assertEqual(expected_diff_keys(RegenSettings(), self.record), set())


class CompareTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_identical_images_match(self):
        a = write_nai_png(self.tmp / "a.png")
        b = write_nai_png(self.tmp / "b.png")
        result = compare_with_source(a, b)
        self.assertEqual(result["verdict"], "match")
        self.assertEqual(result["similarity"], 1.0)
        self.assertEqual(result["dhash_distance"], 0)

    def test_param_diff_and_expected_keys(self):
        a = write_nai_png(self.tmp / "a.png")
        b = write_nai_png(self.tmp / "b.png", seed=77)
        self.assertEqual(compare_with_source(a, b)["verdict"], "param_diff")
        result = compare_with_source(a, b, expected_keys={"seed"})
        self.assertEqual(result["verdict"], "match")
        self.assertTrue(all(diff["expected"] for diff in result["diffs"]))

    def test_web_ui_only_differences_are_benign(self):
        a = write_nai_png(self.tmp / "a.png", uc="", my_flag=True)
        b = write_nai_png(self.tmp / "b.png", uc="lowres")
        result = compare_with_source(a, b)
        self.assertEqual(result["verdict"], "match")
        self.assertEqual(result["param_diff_count"], 0)
        self.assertEqual({d["key"] for d in result["diffs"] if d.get("note")}, {"uc", "my_flag"})

        c = write_nai_png(self.tmp / "c.png", uc="something else")
        self.assertEqual(compare_with_source(a, c)["verdict"], "param_diff")

    def test_client_extra_keys_are_benign(self):
        # NAI Smart Studio 之类的客户端在 Comment 里另记一份负面、角色提示词、CFG；API 出图不回写。
        a = write_nai_png(
            self.tmp / "a.png",
            negative_prompt="lowres",
            char_prompts=["girl"],
            cfg_scale=5.0,
            tag_hint_qt=1,
        )
        b = write_nai_png(self.tmp / "b.png", tag_hint_qt=None)
        result = compare_with_source(a, b)
        self.assertEqual(result["verdict"], "match")
        self.assertEqual(
            {d["key"] for d in result["diffs"] if d.get("note")},
            {"negative_prompt", "char_prompts", "cfg_scale", "tag_hint_qt"},
        )
        # 生成图多出来的键、值不同的键仍然算差异。
        c = write_nai_png(self.tmp / "c.png", tag_hint_qt=None, cfg_rescale=0.5)
        self.assertEqual(compare_with_source(a, c)["verdict"], "param_diff")

    def test_v5_source_label_gives_model(self):
        from tags_machine_core.verification.render_params import normalize_render_parameters

        def model(source):
            return normalize_render_parameters({"png_text": {"Source": source, "Comment": "{}"}})["model"]

        self.assertEqual(model("NovelAI Diffusion V5 0ADF9AB7"), "nai-diffusion-5-full")
        self.assertEqual(model("NovelAI Diffusion V4.5 4BDE2A90"), "nai-diffusion-4-5-full")
        self.assertEqual(model("NovelAI Diffusion V5 DB276663"), "nai-diffusion-5-curated")
        self.assertEqual(model("NovelAI Diffusion V4.5 C02D4F98"), "nai-diffusion-4-5-curated")
        self.assertEqual(model("NovelAI Diffusion V4 5AB81C7C"), "nai-diffusion-4-5-curated")
        self.assertEqual(model("NovelAI Diffusion V5 26E45D15"), "nai-diffusion-5-curated")

    def test_drift_when_params_match_but_pixels_differ(self):
        a = write_nai_png(self.tmp / "a.png", color="white")
        b = write_nai_png(self.tmp / "b.png", color="black")
        self.assertLess(image_similarity(a, b)["similarity"], 0.1)
        self.assertEqual(compare_with_source(a, b)["verdict"], "drift")


class _FakeJob:
    def __init__(self, job_id, status="running"):
        self.id = job_id
        self.status = status


class _FakeContext:
    cancel_requested = False

    def __init__(self):
        self.events = []
        self.results = []

    def emit(self, event, payload):
        self.events.append(event)

    def set_result(self, result):
        self.results.append(result)


class _InlineJobManager:
    """直接在当前线程跑 worker，测试不必等线程。"""

    def __init__(self):
        self.jobs = {}

    def submit(self, name, worker, request=None):
        job = _FakeJob(f"job{len(self.jobs)}")
        self.jobs[job.id] = job
        self.pending = worker
        return job

    def get(self, job_id):
        return self.jobs[job_id]


class _FakeGenerationApi:
    def __init__(self, fail_seeds=()):
        self.requests = []
        self.fail_seeds = set(fail_seeds)

    def generate(self, data):
        request = data["render_request"]
        self.requests.append(request)
        if request["seed"] in self.fail_seeds:
            raise RuntimeError("boom")
        out = Path(data["output_dir"]) / f"gen_{request['seed']}.png"
        params = {k: v for k, v in request["params"].items() if k not in {"n_samples"}}
        write_nai_png(out, **params)
        return {"images": [{"path": str(out)}]}


class FriendlyErrorTest(TestCase):
    def test_known_novelai_errors(self):
        from tags_machine_core.style_lab.service import friendly_error

        self.assertIn("token", friendly_error('[novelai] HTTP 401: {"statusCode":401}'))
        self.assertIn("429", friendly_error("HTTP 429 Too Many Requests"))
        self.assertEqual(friendly_error("something else"), "something else")


class StyleLabServiceTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.store = WorkspaceStore(self.tmp / "runtime")
        write_nai_png(self.tmp / "corpus" / "origin" / "2026-01-11_1_a" / "1_p0.png")
        self.info = self.store.open_folder(self.tmp / "corpus")
        self.image_id = self.store.scan(self.info)[0].images[0].id

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_regenerate_runs_items_and_records_compare(self):
        jobs = _InlineJobManager()
        api = _FakeGenerationApi(fail_seeds={1235})
        service = StyleLabService(store=self.store, job_manager=jobs, generation_api=api)
        run = service.start_regenerate(self.info, self.image_id, RegenSettings(count=2))
        self.assertEqual(run["status"], "queued")
        self.assertEqual(run["job_id"], "job0")
        self.assertEqual(run["expected_diff_keys"], ["seed"])

        result = jobs.pending(_FakeContext())
        self.assertEqual(result["status"], "partial")
        first, second = result["items"]
        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(first["compare"]["verdict"], "match")
        self.assertEqual(second["status"], "failed")
        self.assertEqual(second["error"], "boom")
        self.assertEqual([r["seed"] for r in api.requests], [1234, 1235])

        stored = self.store.get_run(self.info, run["id"])
        self.assertEqual(stored["status"], "partial")
        self.assertEqual(self.store.list_runs(self.info, image_id=self.image_id)[0]["id"], run["id"])

    def test_identical_request_is_blocked_until_forced(self):
        from tags_machine_core.style_lab.service import DuplicateRequestError

        jobs = _InlineJobManager()
        service = StyleLabService(store=self.store, job_manager=jobs, generation_api=_FakeGenerationApi())
        first = service.start_regenerate(self.info, self.image_id, RegenSettings())
        # 还在排队时连点第二次，也会被拦下。
        with self.assertRaises(DuplicateRequestError) as caught:
            service.start_regenerate(self.info, self.image_id, RegenSettings())
        self.assertEqual(caught.exception.previous["id"], first["id"])
        jobs.pending(_FakeContext())
        with self.assertRaises(DuplicateRequestError):
            service.start_regenerate(self.info, self.image_id, RegenSettings())

        # 换了种子就是不同的请求；确认后带 force 也可以重发。
        service.start_regenerate(self.info, self.image_id, RegenSettings(seed_mode="fixed", seed=9))
        forced = service.start_regenerate(self.info, self.image_id, RegenSettings(seed_mode="fixed", seed=9), force=True)
        self.assertEqual(len(self.store.list_runs(self.info, image_id=self.image_id)), 3)

    def test_failed_identical_request_can_be_retried(self):
        jobs = _InlineJobManager()
        service = StyleLabService(
            store=self.store, job_manager=jobs, generation_api=_FakeGenerationApi(fail_seeds={1234})
        )
        service.start_regenerate(self.info, self.image_id, RegenSettings())
        self.assertEqual(jobs.pending(_FakeContext())["status"], "failed")
        service.start_regenerate(self.info, self.image_id, RegenSettings())

    def test_reconcile_marks_orphaned_runs_interrupted(self):
        jobs = _InlineJobManager()
        service = StyleLabService(store=self.store, job_manager=jobs, generation_api=_FakeGenerationApi())
        run = service.start_regenerate(self.info, self.image_id, RegenSettings())
        jobs.jobs.clear()
        reconciled = service.reconcile_run(self.info, self.store.get_run(self.info, run["id"]))
        self.assertEqual(reconciled["status"], "interrupted")
        self.assertEqual(reconciled["items"][0]["status"], "interrupted")


class ClassifyAndGroupingTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_rule_categories(self):
        from tags_machine_core.style_lab.classify import rule_category

        self.assertEqual(rule_category("1girl"), "count")
        self.assertEqual(rule_category("solo"), "count")
        self.assertEqual(rule_category("best quality"), "quality")
        self.assertEqual(rule_category("16k resolution"), "quality")
        self.assertEqual(rule_category("year 2023"), "meta")
        self.assertIsNone(rule_category("silver hair"))

    def test_token_category(self):
        from tags_machine_core.style_lab.classify import token_category

        categories = {"shirabi": "artist", "akipeko": "artist", "silver hair": "appearance", "smooth shading": "style"}
        self.assertEqual(token_category("artist:[[unknown name]]", {}), "artist")
        self.assertEqual(token_category("[[akipeko]]", categories), "artist")
        self.assertEqual(token_category("1.2::silver hair, akipeko::", categories), "artist")
        self.assertEqual(token_category("smooth shading", categories), "style")
        self.assertIsNone(token_category("mystery", categories))

    def _image(self, post_dir, name, prompt, **params):
        path = write_nai_png(self.tmp / post_dir / name, prompt=prompt, v4_prompt=None, **params)
        return build_image_record(path, base=self.tmp)

    def test_groups_cluster_posts_by_artist_stack_then_vibe_and_model(self):
        from tags_machine_core.style_lab.grouping import build_groups

        categories = {"shirabi": "artist", "akipeko": "artist", "ame": "artist", "other artist": "artist", "silver hair": "appearance"}
        images = [
            self._image("2026-01-01_1_a", "1.png", "shirabi, [[akipeko]], 1girl, silver hair"),
            self._image("2026-01-01_1_a", "2.png", "shirabi, [[akipeko]], 1girl"),
            self._image("2026-01-02_2_b", "1.png", "shirabi, [[akipeko]], ame, 1girl"),
            self._image("2026-01-03_3_c", "1.png", "artist:other artist, 1girl", reference_image_multiple=["AAAA"], reference_strength_multiple=[0.5]),
            self._image("2026-01-04_4_d", "1.png", "1girl, silver hair"),
        ]
        groups = build_groups(images, categories)
        self.assertEqual([g["id"] for g in groups], ["g1", "g2", "unassigned"])
        main = groups[0]
        self.assertEqual((main["post_count"], main["image_count"]), (2, 3))
        self.assertTrue(main["name"].startswith("shirabi · akipeko") or main["name"].startswith("akipeko · shirabi"))
        self.assertEqual(main["date_from"], "2026-01-01")
        self.assertEqual(main["children"][0]["vibe"], "no_vibe")
        self.assertTrue(groups[1]["children"][0]["vibe"].startswith("vibe_"))
        self.assertEqual(groups[2]["name"], "未识别画风栈")

    def test_stable_artist_variants_split_inside_a_family(self):
        from tags_machine_core.style_lab.grouping import build_groups

        categories = {"a": "artist", "b": "artist", "c": "artist", "azuuru": "artist", "once": "artist"}
        images = []
        for index in range(4):
            images.append(self._image(f"2026-01-0{index + 1}_{index}_p", "1.png", "artist:[[a, b, c]], 1girl"))
        for index in range(3):
            images.append(self._image(f"2026-02-0{index + 1}_{index + 10}_p", "1.png", "artist:[[a, b, c, azuuru]], 1girl"))
        images.append(self._image("2026-03-01_99_p", "1.png", "artist:[[a, b, c, once]], 1girl"))
        groups = build_groups(images, categories)
        self.assertEqual(len(groups), 1)
        variants = [(child["variant"], child["post_count"]) for child in groups[0]["children"]]
        self.assertEqual(variants, [("基础栈", 5), ("+azuuru", 3)])


class RecipeTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        path = write_nai_png(
            self.tmp / "2026-01-01_1_t" / "a.png",
            prompt="shirabi|[[akipeko]], 1girl, sitting, smooth shading",
            v4_prompt=None,
            uc="lowres, bad hands",
            v4_negative_prompt=None,
            reference_image_multiple=["VIBEDATA"],
            reference_strength_multiple=[0.6],
            reference_information_extracted_multiple=[1.0],
        )
        self.record = build_image_record(path, base=self.tmp)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_recipe_from_image_starts_in_split_stage(self):
        from tags_machine_core.style_lab.recipe import recipe_from_image, tokens_text

        recipe = recipe_from_image(self.record)
        self.assertEqual(recipe.stage, "split")
        self.assertEqual([t.text for t in recipe.subject], ["shirabi", "[[akipeko]]", "1girl", "sitting", "smooth shading"])
        self.assertEqual(tokens_text(recipe.subject), "shirabi|[[akipeko]], 1girl, sitting, smooth shading")
        self.assertEqual(tokens_text(recipe.negative), "lowres, bad hands")
        self.assertEqual(recipe.params["steps"], 28)
        self.assertNotIn("width", recipe.params)
        self.assertNotIn("seed", recipe.params)
        self.assertTrue(recipe.use_source_vibe)
        self.assertIn("not_quailty_prompts", recipe.flags)

    def test_artist_node_matches_tags_txt_shape(self):
        from tags_machine_core.style_lab.recipe import artist_node, recipe_from_image

        recipe = recipe_from_image(self.record)
        recipe.prefix, recipe.subject, recipe.suffix = recipe.subject[:2], recipe.subject[2:4], recipe.subject[4:]
        node = artist_node(recipe, source_path=self.record.path)["renderers"]["novelai"]
        self.assertEqual(node["prompt_prefix"], ["shirabi|[[akipeko]]"])
        self.assertEqual(node["prompt_suffix"], ["smooth shading"])
        self.assertEqual(node["negative_prompt"], ["lowres, bad hands"])
        self.assertEqual(node["params"]["reference_image_multiple"], ["VIBEDATA"])
        self.assertEqual(node["params"]["model"], "nai-diffusion-4-5-full")
        recipe.use_source_vibe = False
        node = artist_node(recipe, source_path=self.record.path)["renderers"]["novelai"]
        self.assertNotIn("reference_image_multiple", node["params"])
        self.assertNotIn("reference_strength_multiple", node["params"])

    def test_store_versions_and_conflicts(self):
        from tags_machine_core.style_lab.recipe import RecipeConflictError, RecipeStore, recipe_from_image

        store = RecipeStore(self.tmp / ".stylelab")
        recipe = store.create(recipe_from_image(self.record, name="测试"))
        saved = store.save(recipe.model_copy(update={"name": "改名"}), base_version=1)
        self.assertEqual((saved.version, saved.name), (2, "改名"))
        with self.assertRaises(RecipeConflictError):
            store.save(recipe, base_version=1)
        self.assertEqual(store.get_version(recipe.id, 1).name, "测试")
        self.assertEqual([item["version"] for item in store.history(recipe.id)], [1])
        self.assertEqual([item.id for item in store.list()], [recipe.id])
