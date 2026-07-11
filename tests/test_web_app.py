import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from unittest import TestCase

from tags_machine_core.web import create_app
from tags_machine_core.web.app import resolve_web_config_path


class WebAppTest(TestCase):
    def test_health_endpoint_returns_ok(self):
        client = TestClient(create_app())

        response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "schema": "tags-machine-core.web.health/v1",
                "status": "ok",
            },
        )

    def test_backend_support_endpoint_exposes_novelai(self):
        client = TestClient(create_app())

        response = client.get("/api/backend-support")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["schema"], "tags-machine-core.backend-support/v1")
        self.assertIn("novelai", data["render_plan_backends"])
        self.assertTrue(any(item["backend"] == "novelai" for item in data["items"]))

    def test_resolve_web_config_path_priority(self):
        original_cwd = Path.cwd()
        original_env = os.environ.pop("TAGS_MACHINE_CONFIG", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "configs").mkdir()
                local = root / "configs" / "local.yaml"
                local.write_text("legacy: {}\n", encoding="utf-8")
                try:
                    os.chdir(root)

                    self.assertEqual(resolve_web_config_path(), Path("configs/local.yaml"))

                    os.environ["TAGS_MACHINE_CONFIG"] = "configs/from-env.yaml"
                    self.assertEqual(resolve_web_config_path(), Path("configs/from-env.yaml"))

                    self.assertEqual(
                        resolve_web_config_path("configs/explicit.yaml"),
                        Path("configs/explicit.yaml"),
                    )
                finally:
                    os.chdir(original_cwd)
        finally:
            os.chdir(original_cwd)
            if original_env is not None:
                os.environ["TAGS_MACHINE_CONFIG"] = original_env
            else:
                os.environ.pop("TAGS_MACHINE_CONFIG", None)
