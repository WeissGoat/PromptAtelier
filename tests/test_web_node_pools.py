import tempfile
from pathlib import Path
from unittest import TestCase

import yaml
from fastapi.testclient import TestClient

from tags_machine_core.web import create_app


class WebNodePoolTest(TestCase):
    def _node(self, root: Path, name: str, classify: dict | None = None) -> Path:
        path = root / name
        path.mkdir(parents=True)
        (path / "meta.yaml").write_text(
            yaml.safe_dump({
                "schema": "tags-machine-core.node/v1",
                "kind": "action",
                "id": name,
                "name": name,
                "prompt": {
                    "positive": [{"text": f"{name}, standing"}],
                    "negative": [],
                },
            }, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        if classify is not None:
            (path / "classify.yaml").write_text(
                yaml.safe_dump(classify, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        return path

    def _client(self, root: Path, collection_file: Path) -> TestClient:
        config = root / "local.yaml"
        config.write_text(yaml.safe_dump({
            "legacy": {"tags_machine_root": str(root), "design_root": str(root / "design")},
            "web": {"project_requires": [str(collection_file)]},
        }, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return TestClient(create_app(config_path=config))

    def test_scan_filters_and_pages_action_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actions = root / "design" / "动作改2"
            foot = self._node(actions, "foot_action", {
                "phase": "core", "species": "human", "cast": "1boy1girl",
                "domain": ["foot"], "subtype": {"foot": ["sole_focus"]},
                "pose": [], "environment": [], "tone": "normal", "flags": [],
                "clothing": "clothed",
            })
            self._node(actions, "mouth_action", {
                "phase": "core", "species": "human", "cast": "1boy1girl",
                "domain": ["mouth"], "subtype": {"mouth": ["oral"]},
                "pose": [], "environment": [], "tone": "normal", "flags": [],
                "clothing": "nude",
            })
            collections = root / "collections.yaml"
            collections.write_text(yaml.safe_dump({
                "collections": {"actions": {"all_actions": [str(actions)]}},
            }, allow_unicode=True, sort_keys=False), encoding="utf-8")
            client = self._client(root, collections)

            response = client.post("/api/node-pools/scan", json={
                "role": "action",
                "spec": {
                    "source": {"type": "collection", "value": "all_actions"},
                    "filters": {"classify": {"domain": ["foot"], "subtype": ["sole_focus"]}},
                },
                "limit": 1,
            })

            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data["total"], 1)
            self.assertEqual(data["items"][0]["ref"], str(foot.resolve()))
            self.assertEqual(data["stats"]["classify_mismatch"], 1)
            self.assertIn("sole_focus", data["facets"]["subtype"])

    def test_sample_returns_full_nodes_without_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actions = root / "design" / "动作改2"
            self._node(actions, "a")
            self._node(actions, "b")
            collections = root / "collections.yaml"
            collections.write_text(yaml.safe_dump({"collections": {}}, sort_keys=False), encoding="utf-8")
            client = self._client(root, collections)

            response = client.post("/api/node-pools/sample", json={
                "role": "action",
                "spec": {"source": {"type": "folder", "value": "动作改2"}},
                "count": 2,
            })

            self.assertEqual(response.status_code, 200, response.text)
            items = response.json()["items"]
            self.assertEqual(len(items), 2)
            self.assertEqual(len({item["candidate"]["ref"] for item in items}), 2)
            self.assertTrue(all(item["node"]["kind"] == "action" for item in items))

    def test_collection_endpoint_uses_project_requires(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "design").mkdir()
            collections = root / "collections.yaml"
            collections.write_text(yaml.safe_dump({
                "collections": {"actions": {"foot": ["动作改2/foot"]}},
            }, allow_unicode=True, sort_keys=False), encoding="utf-8")
            client = self._client(root, collections)

            response = client.get("/api/node-pools/collections", params={"role": "action"})

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["items"], [{"name": "foot", "item_count": 1}])
