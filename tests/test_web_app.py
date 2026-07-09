from fastapi.testclient import TestClient
from unittest import TestCase

from tags_machine_core.web import create_app


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
