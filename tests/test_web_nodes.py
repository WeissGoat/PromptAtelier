from pathlib import Path
from unittest import TestCase

import yaml
from fastapi.testclient import TestClient

from tags_machine_core.web import create_app
from tags_machine_core.web.services.node_workspace import NodeWorkspace


def _write_meta(path: Path, *, kind: str, node_id: str, prompt: str) -> None:
    path.mkdir(parents=True)
    (path / "meta.yaml").write_text(
        yaml.safe_dump(
            {
                "kind": kind,
                "id": node_id,
                "name": node_id,
                "prompt": {"positive": [prompt]},
                "tags": {"default": [prompt]},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


class WebNodesTest(TestCase):
    def test_node_workspace_lists_and_reads_nodes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "design"
            _write_meta(
                design / "角色" / "homura",
                kind="character",
                node_id="homura",
                prompt="akemi_homura",
            )
            workspace = NodeWorkspace(design_root=design)

            nodes = workspace.list_nodes("character", query="homura")
            loaded = workspace.read_node(nodes[0]["ref"])

            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0]["name"], "homura")
            self.assertEqual(loaded["node"]["id"], "homura")
            self.assertEqual(loaded["form"]["prompt"]["positive"], ["akemi_homura"])

    def test_node_workspace_recursively_lists_nested_nodes_with_query_and_limit(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "design"
            _write_meta(
                design / "角色" / "madoka_magica" / "akemi_homura",
                kind="character",
                node_id="homura",
                prompt="akemi_homura",
            )
            _write_meta(
                design / "动作改2" / "st_foot" / "圆神足部闻香",
                kind="action",
                node_id="foot_smell",
                prompt="foot smell",
            )
            workspace = NodeWorkspace(design_root=design)

            characters = workspace.list_nodes("character", query="homura", limit=10)
            actions = workspace.list_nodes("action", query="足部", limit=10)

            self.assertEqual(len(characters), 1)
            self.assertEqual(characters[0]["name"], "akemi_homura")
            self.assertEqual(characters[0]["relative"], "madoka_magica/akemi_homura")
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["name"], "圆神足部闻香")
            self.assertEqual(actions[0]["relative"], "st_foot/圆神足部闻香")

    def test_nodes_http_recursively_lists_nested_nodes_and_honors_limit(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            design = Path(tmp) / "design"
            _write_meta(
                design / "characters" / "series-a" / "alpha",
                kind="character",
                node_id="alpha",
                prompt="alpha",
            )
            _write_meta(
                design / "characters" / "series-b" / "beta",
                kind="character",
                node_id="beta",
                prompt="beta",
            )
            client = TestClient(create_app(node_workspace=NodeWorkspace(design_root=design)))

            response = client.get(
                "/api/nodes",
                params={"role": "character", "q": "series", "limit": 1},
            )

            self.assertEqual(response.status_code, 200)
            nodes = response.json()["nodes"]
            self.assertEqual(len(nodes), 1)
            self.assertIn(nodes[0]["relative"], {"series-a/alpha", "series-b/beta"})

    def test_save_node_accepts_relative_and_in_root_absolute_targets(self):
        import tempfile

        node = {
            "kind": "character",
            "id": "draft",
            "prompt": {"positive": ["draft_tag"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            design = Path(tmp) / "design"
            workspace = NodeWorkspace(design_root=design)

            relative = workspace.save_node("characters/new-relative", node)
            absolute_target = design / "characters" / "new-absolute"
            absolute = workspace.save_node(absolute_target, node)

            self.assertEqual(
                Path(relative["ref"]),
                (design / "characters" / "new-relative").resolve(),
            )
            self.assertEqual(Path(absolute["ref"]), absolute_target.resolve())
            self.assertTrue((design / "characters" / "new-relative" / "meta.yaml").exists())
            self.assertTrue((absolute_target / "meta.yaml").exists())

    def test_save_node_rejects_targets_outside_design_root(self):
        import tempfile

        node = {
            "kind": "character",
            "id": "draft",
            "prompt": {"positive": ["draft_tag"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "design"
            workspace = NodeWorkspace(design_root=design)

            with self.assertRaises(ValueError):
                workspace.save_node("../escaped", node)
            with self.assertRaises(ValueError):
                workspace.save_node(root / "outside", node)

            self.assertFalse((root / "escaped" / "meta.yaml").exists())
            self.assertFalse((root / "outside" / "meta.yaml").exists())

    def test_save_node_http_returns_json_error_for_target_outside_design_root(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = NodeWorkspace(design_root=root / "design")
            client = TestClient(create_app(node_workspace=workspace))

            response = client.put(
                "/api/nodes/save",
                json={
                    "ref": str(root / "outside"),
                    "node": {
                        "kind": "character",
                        "id": "draft",
                        "prompt": {"positive": ["draft_tag"]},
                    },
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "invalid_node")

    def test_preview_node_returns_normalized_node(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design = root / "design"
            _write_meta(
                design / "角色" / "homura",
                kind="character",
                node_id="homura",
                prompt="akemi_homura",
            )
            workspace = NodeWorkspace(design_root=design)
            client = TestClient(create_app(node_workspace=workspace))

            response = client.post(
                "/api/nodes/preview",
                json={
                    "node": {
                        "kind": "character",
                        "id": "draft",
                        "prompt": {"positive": ["draft_tag"]},
                    }
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["node"]["kind"], "character")
            self.assertEqual(response.json()["form"]["prompt"]["positive"], ["draft_tag"])
            self.assertFalse((design / "角色" / "draft").exists())

    def test_preview_node_returns_json_error_for_invalid_node(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            workspace = NodeWorkspace(design_root=Path(tmp) / "design")
            client = TestClient(create_app(node_workspace=workspace))

            response = client.post("/api/nodes/preview", json={"node": {"kind": "character"}})

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "invalid_node")
