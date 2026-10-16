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


def write_png(path: Path, *, seed: int, timing: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    info = PngInfo()
    info.add_text("tags_machine_core", json.dumps({
        "backend": "comfyui",
        "nodes": [{"role": "action", "id": "F:\\design\\动作\\standing"}],
        "render": {"seed": seed, "width": 64, "height": 96},
        "timing": timing,
    }))
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
