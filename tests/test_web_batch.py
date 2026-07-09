from pathlib import Path
from unittest import TestCase

import yaml
from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.batch_workspace import BatchWorkspace


def _write_node(path: Path, *, kind: str, node_id: str, prompt: str):
    path.mkdir(parents=True)
    (path / "meta.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": kind,
                "id": node_id,
                "name": node_id,
                "prompt": {"positive": [prompt]},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


class WebBatchTest(TestCase):
    def test_batch_preview_returns_summary(self):
        self._write_demo_nodes()
        workspace = BatchWorkspace(base_dir=self.tmp_path)

        result = workspace.preview({"spec": self._demo_spec()})

        self.assertEqual(result["task_count"], 1)
        self.assertTrue(result["sample_tasks"][0]["source"]["character"].endswith("homura"))

    def test_batch_preview_http(self):
        self._write_demo_nodes()
        client = TestClient(create_app(batch_workspace=BatchWorkspace(base_dir=self.tmp_path)))

        response = client.post("/api/batches/preview", json={"spec": self._demo_spec()})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["task_count"], 1)

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_demo_nodes(self):
        _write_node(
            self.tmp_path / "characters" / "homura",
            kind="character",
            node_id="homura",
            prompt="akemi_homura",
        )
        _write_node(
            self.tmp_path / "actions" / "standing",
            kind="action",
            node_id="standing",
            prompt="standing",
        )

    def _demo_spec(self) -> dict:
        return {
            "name": "demo",
            "defaults": {"composer": "script", "artist": "20260412"},
            "select": {
                "characters": [
                    {
                        "selector": "explicit",
                        "refs": [str(self.tmp_path / "characters" / "homura")],
                    }
                ],
                "actions": [
                    {
                        "selector": "explicit",
                        "refs": [str(self.tmp_path / "actions" / "standing")],
                    }
                ],
            },
            "expand": {"mode": "product"},
        }
