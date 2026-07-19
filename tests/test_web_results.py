import json
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from tags_machine_core.web import create_app
from tags_machine_core.web.services.result_index import ResultIndex


class WebResultsTest(TestCase):
    def _write_png(self, path, *, seed: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        png_info = PngInfo()
        png_info.add_text(
            "Comment",
            json.dumps(
                {
                    "seed": seed,
                    "model": "nai-diffusion-4-5-full",
                    "sampler": "k_euler",
                    "steps": 28,
                }
            ),
        )
        png_info.add_text("Source", "NovelAI V4.5")
        Image.new("RGB", (64, 96), "white").save(path, pnginfo=png_info)

    def test_result_index_lists_runs_and_task_files(self):
        run = self.tmp_path / "runs" / "demo"
        task = run / "tasks" / "task_1"
        task.mkdir(parents=True)
        (task / "generation_result.json").write_text(
            json.dumps({"images": [{"path": "a.png"}]}),
            encoding="utf-8",
        )
        (task / "prompt_bundle.json").write_text(
            json.dumps({"prompt": {"positive": "1girl"}}),
            encoding="utf-8",
        )
        index = ResultIndex(roots=[self.tmp_path / "runs"])

        runs = index.list_runs()
        task_data = index.get_task(task)

        self.assertEqual(runs[0]["name"], "demo")
        self.assertTrue(task_data["files"]["generation_result"].endswith("generation_result.json"))

    def test_results_http_serves_json_file(self):
        run = self.tmp_path / "runs" / "demo"
        task = run / "tasks" / "task_1"
        task.mkdir(parents=True)
        result_path = task / "generation_result.json"
        result_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
        client = TestClient(create_app(result_index=ResultIndex(roots=[self.tmp_path / "runs"])))

        response = client.get("/api/results/file", params={"path": str(result_path)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_results_http_serves_rooted_image_and_rejects_unsafe_paths(self):
        root = self.tmp_path / "outputs"
        image = root / "demo" / "tasks" / "task_1" / "generated.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"png-bytes")
        outside = self.tmp_path / "outside.png"
        outside.write_bytes(b"outside")
        (root / "demo" / "notes.txt").write_text("not an image", encoding="utf-8")
        (root / "demo" / "folder.png").mkdir()
        client = TestClient(create_app(result_index=ResultIndex(roots=[root])))

        response = client.get(
            "/api/results/image",
            params={"path": "demo/tasks/task_1/generated.png"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"png-bytes")
        prefixed_response = client.get(
            "/api/results/image",
            params={"path": "outputs/demo/tasks/task_1/generated.png"},
        )
        self.assertEqual(prefixed_response.status_code, 200)
        self.assertEqual(prefixed_response.content, b"png-bytes")
        for unsafe_path in (
            "../outside.png",
            str(outside),
            "demo/notes.txt",
            "demo/folder.png",
        ):
            with self.subTest(path=unsafe_path):
                rejected = client.get("/api/results/image", params={"path": unsafe_path})
                self.assertEqual(rejected.status_code, 404)

    def test_image_metadata_is_read_from_the_current_png_file(self):
        root = self.tmp_path / "outputs"
        image = root / "generated.png"
        self._write_png(image, seed=111)
        client = TestClient(create_app(result_index=ResultIndex(roots=[root])))

        first = client.get(
            "/api/results/image-metadata",
            params={"path": "generated.png"},
        )
        self._write_png(image, seed=222)
        second = client.get(
            "/api/results/image-metadata",
            params={"path": "generated.png"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["parameters"]["seed"], 111)
        self.assertEqual(second.json()["parameters"]["seed"], 222)
        self.assertEqual(second.json()["model"], "nai-diffusion-4-5-full")
        self.assertEqual(second.json()["dimensions"], {"width": 64, "height": 96})
        self.assertEqual(second.json()["png_text"]["Source"], "NovelAI V4.5")

    def test_image_metadata_rejects_paths_outside_result_roots(self):
        root = self.tmp_path / "outputs"
        root.mkdir()
        outside = self.tmp_path / "outside.png"
        self._write_png(outside, seed=1)
        client = TestClient(create_app(result_index=ResultIndex(roots=[root])))

        response = client.get(
            "/api/results/image-metadata",
            params={"path": str(outside)},
        )

        self.assertEqual(response.status_code, 404)

    def test_image_metadata_uses_png_source_when_comment_has_no_model(self):
        root = self.tmp_path / "outputs"
        image = root / "generated.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        png_info = PngInfo()
        png_info.add_text("Comment", json.dumps({"seed": 444}))
        png_info.add_text("Source", "NovelAI Diffusion V4.5 4BDE2A90")
        Image.new("RGB", (64, 96), "white").save(image, pnginfo=png_info)
        client = TestClient(create_app(result_index=ResultIndex(roots=[root])))

        response = client.get(
            "/api/results/image-metadata",
            params={"path": "generated.png"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"], "NovelAI Diffusion V4.5 4BDE2A90")

    def test_image_parameter_diff_reads_and_normalizes_both_png_files(self):
        root = self.tmp_path / "outputs"
        previous = root / "previous.png"
        current = root / "current.png"
        previous.parent.mkdir(parents=True, exist_ok=True)
        previous_info = PngInfo()
        previous_info.add_text(
            "Comment",
            json.dumps(
                {
                    "seed": 111,
                    "sampler": "k_euler",
                    "prompt": "first prompt",
                    "reference_image_multiple": ["first-image-data"],
                }
            ),
        )
        current_info = PngInfo()
        current_info.add_text(
            "Comment",
            json.dumps(
                {
                    "seed": 222,
                    "sampler": "k_euler_ancestral",
                    "prompt": "second prompt",
                    "reference_image_multiple": ["second-image-data"],
                }
            ),
        )
        Image.new("RGB", (64, 96), "white").save(previous, pnginfo=previous_info)
        Image.new("RGB", (64, 96), "white").save(current, pnginfo=current_info)
        client = TestClient(create_app(result_index=ResultIndex(roots=[root])))

        response = client.get(
            "/api/results/image-parameter-diff",
            params={"previous_path": "previous.png", "current_path": "current.png"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["match"])
        paths = {item["path"] for item in data["diffs"]}
        self.assertIn("$.parameters.seed", paths)
        self.assertIn("$.parameters.sampler", paths)
        reference = data["current_normalized"]["parameters"]["reference_image_multiple"][0]
        self.assertEqual(reference["type"], "string")
        self.assertIn("sha256", reference)
        self.assertNotIn("second-image-data", json.dumps(data))

    def test_image_parameter_diff_rejects_an_image_outside_result_roots(self):
        root = self.tmp_path / "outputs"
        previous = root / "previous.png"
        outside = self.tmp_path / "outside.png"
        self._write_png(previous, seed=1)
        self._write_png(outside, seed=2)
        client = TestClient(create_app(result_index=ResultIndex(roots=[root])))

        response = client.get(
            "/api/results/image-parameter-diff",
            params={"previous_path": "previous.png", "current_path": str(outside)},
        )

        self.assertEqual(response.status_code, 404)

    @patch("tags_machine_core.web.routes.results.subprocess.Popen")
    @patch("tags_machine_core.web.routes.results.sys.platform", "win32")
    def test_open_image_folder_selects_the_resolved_image(self, popen):
        root = self.tmp_path / "outputs"
        image = root / "generated.png"
        self._write_png(image, seed=333)
        client = TestClient(create_app(result_index=ResultIndex(roots=[root])))

        response = client.post(
            "/api/results/open-image-folder",
            json={"path": "generated.png"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["opened"])
        popen.assert_called_once_with(
            ["explorer.exe", "/select,", str(image.resolve())],
            close_fds=True,
        )

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
