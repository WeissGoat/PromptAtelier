from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase
from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.routes import compare


class WebCompareTest(TestCase):
    def setUp(self):
        self.original_autosave_path = compare.AUTOSAVE_PATH
        self.test_autosave_path = Path("output") / ".test_compare_workspace_autosave.json"
        compare.AUTOSAVE_PATH = self.test_autosave_path
        if self.test_autosave_path.exists():
            self.test_autosave_path.unlink()

    def tearDown(self):
        if self.test_autosave_path.exists():
            self.test_autosave_path.unlink()
        compare.AUTOSAVE_PATH = self.original_autosave_path

    def test_get_compare_workspace_404_when_missing(self):
        client = TestClient(create_app())
        resp = client.get("/api/compare/workspace")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "workspace_not_found")

    def test_save_and_get_compare_workspace(self):
        client = TestClient(create_app())
        payload = {
            "schema": "promptatelier.compare-workspace/v1",
            "rounds": [{"id": "r1", "name": "Batch 1", "variants": []}],
        }
        post_resp = client.post("/api/compare/workspace", json=payload)
        self.assertEqual(post_resp.status_code, 200)
        self.assertEqual(post_resp.json()["status"], "saved")
        self.assertEqual(post_resp.json()["round_count"], 1)

        get_resp = client.get("/api/compare/workspace")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["rounds"][0]["name"], "Batch 1")

    def test_clear_compare_workspace(self):
        client = TestClient(create_app())
        payload = {
            "schema": "promptatelier.compare-workspace/v1",
            "rounds": [{"id": "r1", "name": "Batch 1", "variants": []}],
        }
        client.post("/api/compare/workspace", json=payload)
        del_resp = client.delete("/api/compare/workspace")
        self.assertEqual(del_resp.status_code, 200)
        self.assertFalse(self.test_autosave_path.exists())
