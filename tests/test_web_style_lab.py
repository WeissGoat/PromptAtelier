import json
import tempfile
import time
from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient

from tags_machine_core.config import LLMConfig
from tags_machine_core.contracts import GeneratedImage, GenerationResult
from tags_machine_core.llm import LLMCache, LLMClient
from tags_machine_core.web import create_app

from tests.test_style_lab import write_nai_png


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _TranslateSession:
    def __init__(self):
        self.calls = 0

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        tags = __import__("json").loads(json["messages"][1]["content"])
        content = __import__("json").dumps({"translations": {tag: f"译:{tag}" for tag in tags}}, ensure_ascii=False)
        return _Response({"data": {"choices": [{"message": {"content": content}}]}})


def _fake_executor(request, options):
    out_dir = Path(options["output_dir"])
    out = out_dir / f"gen_{request.seed}.png"
    write_nai_png(out, **{k: v for k, v in request.params.items() if k != "n_samples"})
    return GenerationResult(backend="novelai", images=[GeneratedImage(path=out, filename=out.name)])


class WebStyleLabTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        design = self.tmp / "design"
        design.mkdir()
        config = self.tmp / "config.yaml"
        config.write_text(
            json.dumps(
                {
                    "legacy": {"tags_machine_root": str(self.tmp), "design_root": str(design)},
                    "runtime": {"output_dir": str(self.tmp / "outputs"), "cache_dir": str(self.tmp / "cache")},
                }
            ),
            encoding="utf-8",
        )
        self.cache = LLMCache(self.tmp / "llm.sqlite")
        self.session = _TranslateSession()
        llm = LLMClient(LLMConfig(base_url="https://llm.test/v1", api_key="sk"), session=self.session, cache=self.cache)
        self.app = create_app(
            config_path=config,
            generation_executor=_fake_executor,
            llm_client=llm,
            style_lab_dir=self.tmp / "stylelab",
        )
        self.client = TestClient(self.app)
        self.corpus = self.tmp / "20260717" / "105845157"
        write_nai_png(self.corpus / "origin" / "2026-01-11_1_a" / "1_p0.png")
        write_nai_png(self.corpus / "origin" / "2026-01-12_2_b" / "2_p0.png", request_type="NativeInfillingRequest")

    def tearDown(self):
        self.cache.close()
        self.temp_dir.cleanup()

    def _open(self):
        response = self.client.post("/api/style-lab/workspaces", json={"root": str(self.corpus)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _wait_run(self, workspace_id, run_id):
        deadline = time.time() + 10
        while True:
            run = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/runs/{run_id}").json()["run"]
            if run["status"] not in {"queued", "running"} or time.time() > deadline:
                return run
            time.sleep(0.05)

    def test_open_workspace_lists_images_and_serves_files(self):
        data = self._open()
        workspace_id = data["workspace"]["id"]
        self.assertEqual(data["scan"]["read"], 2)
        self.assertEqual(len(data["images"]), 2)
        image = data["images"][0]

        listed = self.client.get("/api/style-lab/workspaces").json()["workspaces"]
        self.assertEqual([item["id"] for item in listed], [workspace_id])

        detail = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/images/{image['id']}").json()
        self.assertEqual(detail["raw_parameters"]["seed"], 1234)
        self.assertIn("Comment", detail["png_text_keys"])

        file_response = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/file?image_id={image['id']}")
        self.assertEqual(file_response.status_code, 200)
        thumb = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/file?image_id={image['id']}&size=160")
        self.assertEqual(thumb.headers["content-type"], "image/webp")

        outside = write_nai_png(self.tmp / "elsewhere.png")
        forbidden = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/file", params={"path": str(outside)})
        self.assertEqual(forbidden.status_code, 403)

    def test_regenerate_creates_run_and_compares(self):
        data = self._open()
        workspace_id = data["workspace"]["id"]
        image_id = data["images"][0]["id"]
        response = self.client.post(
            f"/api/style-lab/workspaces/{workspace_id}/regenerate",
            json={"image_id": image_id, "settings": {"count": 1}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        run_id = response.json()["run"]["id"]

        run = self._wait_run(workspace_id, run_id)
        self.assertEqual(run["status"], "succeeded", run)
        item = run["items"][0]
        self.assertEqual(item["compare"]["verdict"], "match")
        generated = self.client.get(
            f"/api/style-lab/workspaces/{workspace_id}/file", params={"path": item["image_path"], "size": 160}
        )
        self.assertEqual(generated.status_code, 200)

        runs = self.client.get(f"/api/style-lab/workspaces/{workspace_id}/runs?image_id={image_id}").json()["runs"]
        self.assertEqual([r["id"] for r in runs], [run_id])

    def test_regenerate_rejects_bad_settings_and_warns_for_inpaint(self):
        data = self._open()
        workspace_id = data["workspace"]["id"]
        bad = self.client.post(
            f"/api/style-lab/workspaces/{workspace_id}/regenerate",
            json={"image_id": data["images"][0]["id"], "settings": {"seed_mode": "fixed"}},
        )
        self.assertEqual(bad.status_code, 400)
        inpaint = next(img for img in data["images"] if "inpaint" in img["flags"])
        response = self.client.post(
            f"/api/style-lab/workspaces/{workspace_id}/regenerate",
            json={"image_id": inpaint["id"], "settings": {}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["run"]["warnings"])
        self._wait_run(workspace_id, response.json()["run"]["id"])

    def test_translate_and_llm_status(self):
        status = self.client.get("/api/style-lab/llm/status").json()
        self.assertTrue(status["available"])
        self.assertEqual(status["models"]["text"], "deepseek-4.1-flash")
        response = self.client.post("/api/style-lab/translate", json={"texts": ["{{thin lines}}", "solo"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["translations"], {"{{thin lines}}": "译:thin lines", "solo": "译:solo"}
        )
        bad = self.client.post("/api/style-lab/translate", json={"texts": "solo"})
        self.assertEqual(bad.status_code, 400)

    def test_open_workspace_pretranslates_prompts_into_cache(self):
        data = self._open()
        job_id = data["pretranslate_job_id"]
        self.assertTrue(job_id)
        self.app.state.job_manager.wait(job_id, timeout=10)
        job = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(job["status"], "succeeded", job)
        calls = self.session.calls
        response = self.client.post("/api/style-lab/translate", json={"texts": ["girl", "silver hair", "lowres"]})
        self.assertEqual(response.json()["translations"]["silver hair"], "译:silver hair")
        self.assertEqual(self.session.calls, calls)

    def test_files_workspace_upload(self):
        created = self.client.post("/api/style-lab/workspaces", json={"files": [], "name": "拖入"}).json()
        workspace_id = created["workspace"]["id"]
        png = write_nai_png(self.tmp / "upload_src.png").read_bytes()
        response = self.client.post(
            f"/api/style-lab/workspaces/{workspace_id}/upload",
            files=[("files", ("drop.png", png, "image/png")), ("files", ("notes.txt", b"x", "text/plain"))],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["uploaded"], 1)
        self.assertEqual(len(response.json()["images"]), 1)
