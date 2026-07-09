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

    def test_nodes_http_preview_does_not_write_file(self):
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
                json={"kind": "character", "id": "draft", "prompt": {"positive": ["draft_tag"]}},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["form"]["prompt"]["positive"], ["draft_tag"])
            self.assertFalse((design / "角色" / "draft").exists())
