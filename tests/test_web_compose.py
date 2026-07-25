from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient

from tags_machine_core.contracts import GeneratedImage, GenerationResult
from tags_machine_core.execution import build_core_png_text
from tags_machine_core.web import create_app


class WebComposeTest(TestCase):
    def test_compose_preview_returns_prompt_bundle_and_render_request(self):
        client = TestClient(create_app())

        response = client.post(
            "/api/compose-preview",
            json={
                "compose": {"prompt": "1girl, standing", "negative": "lowres"},
                "render": {"backend": "novelai", "width": 1024, "height": 1024},
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["prompt_bundle"]["prompt"]["positive"], "1girl, standing")
        self.assertEqual(data["render_request"]["backend"], "novelai")

    def test_generate_endpoint_creates_job_with_injected_executor(self):
        def executor(request, options):
            return GenerationResult(
                backend="novelai",
                images=[
                    GeneratedImage(
                        path=Path("image.png"),
                        filename="image.png",
                        meta={"index": 0},
                    )
                ],
                request_body={"ok": True},
                png_info={"images": []},
                cache_hit=False,
            )

        app = create_app(generation_executor=executor)
        client = TestClient(app)

        preview = client.post(
            "/api/compose-preview",
            json={
                "compose": {"prompt": "1girl, standing"},
                "render": {"backend": "novelai", "width": 1024, "height": 1024},
            },
        ).json()
        response = client.post("/api/generate", json={"render_request": preview["render_request"]})
        job_id = response.json()["id"]
        app.state.job_manager.wait(job_id, timeout=5)
        job = client.get(f"/api/jobs/{job_id}").json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["result"]["images"][0]["filename"], "image.png")

    def test_compose_preview_returns_json_error_for_bad_artist_ref(self):
        client = TestClient(create_app())

        response = client.post(
            "/api/compose-preview",
            json={
                "compose": {"prompt": "1girl, standing"},
                "render": {"backend": "novelai", "artist": "missing_artist_ref"},
            },
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["error"]["code"], "compose_preview_failed")
        self.assertIn("missing_artist_ref", data["error"]["message"])

    def test_generate_attaches_random_selection_to_request_result_and_png_metadata(self):
        captured = {}

        def executor(request, options):
            captured["request"] = request
            return GenerationResult(backend="novelai")

        app = create_app(generation_executor=executor)
        client = TestClient(app)
        selection = {
            "slot_id": "primary-action",
            "role": "action",
            "candidate": {"ref": "actions/foot", "name": "foot"},
        }
        response = client.post("/api/generate", json={
            "render_request": {
                "backend": "novelai",
                "prompt": "1girl, sole focus",
                "negative_prompt": "",
            },
            "random_selections": [selection],
        })
        job_id = response.json()["id"]
        app.state.job_manager.wait(job_id, timeout=5)
        job = client.get(f"/api/jobs/{job_id}").json()

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["result"]["random_selections"], [selection])
        self.assertEqual(captured["request"].meta["random_nodes"], [selection])
        self.assertIn("random_nodes", build_core_png_text(captured["request"])["tags_machine_core"])
