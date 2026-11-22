import json
import os
import tempfile
import time
from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from tags_machine_core.web import create_app
from tags_machine_core.web.services.job_manager import JobManager
from tags_machine_core.web.services.output_history import OutputHistory
from tags_machine_core.web.services.result_index import ResultIndex


def write_png(
    path: Path,
    *,
    seed: int,
    timing: dict | None = None,
    backend: str = "comfyui",
    nodes: list[dict] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    info = PngInfo()
    info.add_text("tags_machine_core", json.dumps({
        "backend": backend,
        "nodes": nodes if nodes is not None else [{"role": "action", "id": "F:\\design\\动作\\standing"}],
        "render": {"seed": seed, "width": 64, "height": 96},
        "timing": timing,
    }, ensure_ascii=False))
    Image.new("RGB", (64, 96), "white").save(path, pnginfo=info)


class OutputHistoryTest(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "outputs"

    def tearDown(self):
        self._tmp.cleanup()

    def test_lists_runs_newest_first_and_groups_loose_images_by_day(self):
        write_png(self.root / "compares" / "random_20261001000000_aaaa" / "group_001_seed_1" / "a.png", seed=1)
        time.sleep(0.05)
        write_png(self.root / "loose.png", seed=9)
        time.sleep(0.05)
        write_png(self.root / "compares" / "compare_20261002000000_bbbb" / "group_002_seed_5" / "b.png", seed=5)
        write_png(self.root / "compares" / "compare_20261002000000_bbbb" / "group_001_seed_4" / "c.png", seed=4)
        write_png(self.root / ".web" / "thumbs" / "hidden.png", seed=0)
        (self.root / "empty_dir").mkdir()

        runs = OutputHistory(self.root).list_runs()

        self.assertEqual(
            [(run["kind"], run["image_count"]) for run in runs],
            [("compare", 2), ("loose", 1), ("random", 1)],
        )
        self.assertEqual(runs[0]["id"], "compares/compare_20261002000000_bbbb")
        self.assertEqual(runs[0]["group_count"], 2)
        self.assertTrue(runs[1]["id"].startswith("loose/"))

    def test_run_images_are_ordered_by_group_with_png_summaries(self):
        run = self.root / "compares" / "compare_20261002000000_bbbb"
        write_png(run / "group_002_seed_5" / "b.png", seed=5)
        write_png(run / "group_001_seed_4" / "c.png", seed=4, timing={"elapsed_seconds": 3.5})
        history = OutputHistory(self.root)

        listing = history.run_images("compares/compare_20261002000000_bbbb")

        self.assertEqual([image["group"] for image in listing["images"]], ["group_001_seed_4", "group_002_seed_5"])
        info = listing["images"][0]["info"]
        self.assertEqual((info["backend"], info["seed"], info["width"]), ("comfyui", 4, 64))
        self.assertEqual(info["nodes"], [{"role": "action", "name": "standing"}])
        self.assertEqual(info["timing"], {"elapsed_seconds": 3.5})
        for bad in ("../outside", "compares/missing", "loose/1999-01-01", str(self.root)):
            with self.assertRaises(FileNotFoundError):
                history.run_images(bad)

    def test_extra_roots_list_each_subdir_as_run(self):
        auto = Path(self._tmp.name) / "design" / "auto"
        write_png(auto / "20261016" / "00001_homura_sitting_bbbb" / "b.png", seed=2)
        write_png(auto / "20261016" / "00000_homura_standing_aaaa" / "a.png", seed=1)
        write_png(self.root / "primary_20261016000000_cccc" / "c.png", seed=3)
        history = OutputHistory(self.root, extra_roots=[auto])

        runs = {run["id"]: run for run in history.list_runs()}

        self.assertEqual(set(runs), {"primary_20261016000000_cccc", "@0/20261016"})
        self.assertEqual((runs["@0/20261016"]["name"], runs["@0/20261016"]["group_count"]), ("auto · 20261016", 2))
        listing = history.run_images("@0/20261016")
        self.assertEqual(
            [image["group"] for image in listing["images"]],
            ["00000_homura_standing_aaaa", "00001_homura_sitting_bbbb"],
        )
        for bad in ("@0/../outputs", "@1/20261016", "@x/20261016", "@0/missing"):
            with self.assertRaises(FileNotFoundError):
                history.run_images(bad)

    def test_extra_roots_listed_when_output_root_missing(self):
        auto = Path(self._tmp.name) / "design" / "auto"
        write_png(auto / "20261016" / "00000_homura_standing_aaaa" / "a.png", seed=1)

        runs = OutputHistory(self.root, extra_roots=[auto]).list_runs()

        self.assertFalse(self.root.exists())
        self.assertEqual([run["id"] for run in runs], ["@0/20261016"])


class HistoryHttpTest(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "outputs"

    def tearDown(self):
        self._tmp.cleanup()

    def test_history_routes_attach_job_labels_and_serve_cached_thumbnails(self):
        run = self.root / "compares" / "random_20261001000000_aaaa"
        image = run / "group_001_seed_1" / "a.png"
        write_png(image, seed=1)
        manager = JobManager()
        job = manager.submit("generate-batch", lambda ctx: {"label": "Random · 1 轮", "output_dir": str(run)})
        manager.wait(job.id, timeout=5)
        thumbs = Path(self._tmp.name) / "thumbs"
        app = create_app(job_manager=manager, result_index=ResultIndex(roots=[self.root], thumb_dir=thumbs))
        app.state.output_history = OutputHistory(self.root)
        client = TestClient(app)

        runs = client.get("/api/history/runs").json()["runs"]
        self.assertEqual(runs[0]["job"]["label"], "Random · 1 轮")
        images = client.get("/api/history/images", params={"run_id": runs[0]["id"]}).json()
        self.assertEqual(images["total"], 1)
        self.assertEqual(client.get("/api/history/images", params={"run_id": "../x"}).status_code, 404)

        thumb = client.get("/api/results/thumb", params={"path": str(image), "size": 200})
        self.assertEqual(thumb.status_code, 200)
        self.assertEqual(thumb.headers["content-type"], "image/webp")
        cached = list(thumbs.rglob("*.webp"))
        self.assertEqual(len(cached), 1)
        with Image.open(cached[0]) as small:
            self.assertEqual(max(small.size), 96)  # 原图比缩略图尺寸还小时不放大
        os.utime(image, None)
        self.assertEqual(client.get("/api/results/thumb", params={"path": str(image), "size": 160}).status_code, 200)
        self.assertEqual(client.get("/api/results/thumb", params={"path": str(Path(self._tmp.name) / "nope.png")}).status_code, 404)

    def test_history_search_and_nodes_filter_across_runs(self):
        run_a = self.root / "compares" / "compare_20261001000000_aaaa"
        run_b = self.root / "compares" / "random_20261002000000_bbbb"
        write_png(
            run_a / "group_001_seed_1" / "a1.png",
            seed=1,
            backend="comfyui",
            nodes=[
                {"role": "artist", "id": "p4", "ref": "artists/p4"},
                {"role": "character", "id": "homura", "ref": "F:\\design\\角色\\homura"},
                {"role": "action", "id": "standing", "ref": "F:\\design\\动作\\standing"},
            ],
        )
        time.sleep(0.02)
        write_png(
            run_a / "group_002_seed_2" / "a2.png",
            seed=2,
            backend="novelai",
            nodes=[
                {"role": "artist", "id": "p4", "ref": "artists/p4"},
                {"role": "character", "id": "madoka", "ref": "F:\\design\\角色\\madoka"},
                {"role": "action", "id": "sitting", "ref": "F:\\design\\动作\\sitting"},
            ],
        )
        time.sleep(0.02)
        # 旧图没有 ref，仅靠 id 也能按 name 回退命中。
        write_png(
            run_b / "group_001_seed_3" / "b1.png",
            seed=3,
            backend="novelai",
            nodes=[
                {"role": "artist", "id": "p5"},
                {"role": "character", "id": "F:\\design\\角色\\homura"},
            ],
        )

        db_path = Path(self._tmp.name) / "history_index.sqlite3"
        app = create_app(result_index=ResultIndex(roots=[self.root]))
        app.state.output_history = OutputHistory(self.root, index_path=db_path)
        client = TestClient(app)

        try:
            # 1) 列出索引到的节点
            chars = client.get("/api/history/nodes", params={"role": "character"}).json()
            self.assertFalse(chars["indexing"]["running"])
            by_name = {item["name"]: item["count"] for item in chars["nodes"]}
            self.assertEqual(by_name["homura"], 2)
            self.assertEqual(by_name["madoka"], 1)

            # 2) 按单节点（含 ref）跨批次筛选，应同时命中 run_a 的带 ref 图和 run_b 的旧图
            res = client.get(
                "/api/history/search",
                params={"nodes": json.dumps([{"role": "character", "name": "homura", "ref": "F:/design/角色/homura"}])},
            ).json()
            self.assertEqual(res["total"], 2)
            self.assertEqual([img["filename"] for img in res["images"]], ["b1.png", "a1.png"])
            self.assertEqual(
                {item["id"]: item["match_count"] for item in res["matched_runs"]},
                {
                    "compares/compare_20261001000000_aaaa": 1,
                    "compares/random_20261002000000_bbbb": 1,
                },
            )
            self.assertEqual(res["backends"], ["comfyui", "novelai"])

            # 3) 多节点 AND 筛选（character=homura + artist=p4）
            combo = client.get(
                "/api/history/search",
                params={
                    "nodes": json.dumps([
                        {"role": "character", "name": "homura", "ref": "F:/design/角色/homura"},
                        {"role": "artist", "name": "p4", "ref": "artists/p4"},
                    ]),
                },
            ).json()
            self.assertEqual(combo["total"], 1)
            self.assertEqual(combo["images"][0]["filename"], "a1.png")

            # 4) 限定 run_id 时，matched_runs 仍保留全部命中批次供侧边栏切换
            narrowed = client.get(
                "/api/history/search",
                params={
                    "nodes": json.dumps([{"role": "character", "name": "homura"}]),
                    "run_id": "compares/compare_20261001000000_aaaa",
                },
            ).json()
            self.assertEqual(narrowed["total"], 1)
            self.assertEqual(narrowed["images"][0]["filename"], "a1.png")
            self.assertEqual(len(narrowed["matched_runs"]), 2)

            # 5) 无效 nodes 参数返回 400
            self.assertEqual(client.get("/api/history/search", params={"nodes": "not-json"}).status_code, 400)
        finally:
            app.state.output_history.close()

    def test_history_search_handles_utf8_text_chunk_and_short_ref_mismatch(self):
        """回归测试：真图用 ensure_ascii=False 写 UTF-8 tEXt（含中文目录如 画风），且有的图存短 ref。"""
        run_a = self.root / "compares" / "primary_20261003000000_cccc"
        write_png(
            run_a / "u1.png",
            seed=10,
            backend="novelai",
            nodes=[{
                "role": "artist",
                "id": "22e5cc071e_ixyv5",
                "ref": "F:\\my_project\\design\\画风\\22e5cc071e_ixyv5",
            }],
        )
        write_png(
            run_a / "u2.png",
            seed=11,
            backend="novelai",
            nodes=[{
                "role": "artist",
                "id": "22e5cc071e_ixyv5",
                "ref": "22e5cc071e_ixyv5",
            }],
        )
        app = create_app(result_index=ResultIndex(roots=[self.root]))
        app.state.output_history = OutputHistory(self.root)
        client = TestClient(app)
        try:
            res = client.get(
                "/api/history/search",
                params={
                    "nodes": json.dumps([{
                        "role": "artist",
                        "name": "22e5cc071e_ixyv5",
                        "ref": "F:\\my_project\\design\\画风\\22e5cc071e_ixyv5",
                    }]),
                },
            ).json()
            self.assertEqual(res["total"], 2)
            self.assertEqual(
                {img["info"]["nodes"][0]["ref"] for img in res["images"]},
                {"F:\\my_project\\design\\画风\\22e5cc071e_ixyv5", "22e5cc071e_ixyv5"},
            )
        finally:
            app.state.output_history.close()
