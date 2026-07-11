import json
from unittest import TestCase

from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.result_index import ResultIndex


class WebResultsTest(TestCase):
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

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
