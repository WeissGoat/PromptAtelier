import os
import tempfile
from pathlib import Path
from unittest import TestCase

import yaml
from fastapi.testclient import TestClient
from PIL import Image

from tags_machine_core.web import create_app
from tags_machine_core.web.services.node_previews import NodePreviewIndex, pick_preview
from tags_machine_core.web.services.node_workspace import NodeWorkspace
from tags_machine_core.web.services.result_index import ResultIndex


def write_node(path: Path, name: str) -> Path:
    path.mkdir(parents=True)
    (path / "meta.yaml").write_text(yaml.safe_dump({
        "schema": "tags-machine-core.node/v1",
        "kind": "action",
        "id": name,
        "name": name,
        "prompt": {"positive": [{"text": name}], "negative": []},
    }, allow_unicode=True), encoding="utf-8")
    return path


def write_image(path: Path, mtime: float, color: str = "white") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 60), color).save(path)
    os.utime(path, (mtime, mtime))
    return path


class PickPreviewTest(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.node = Path(self._tmp.name) / "node"
        self.node.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_prefers_the_earliest_own_image_over_generated_ones(self):
        write_image(self.node / "gen_0001.png", 100)
        write_image(self.node / "blackboard_next.png", 150)
        write_image(self.node / "comm_seed_2.png", 300)
        own = write_image(self.node / "comm_seed_1.png", 200)
        write_image(self.node / "sub" / "older.png", 50)  # 子目录不看

        self.assertEqual(pick_preview(self.node), own)

    def test_falls_back_to_the_earliest_image_of_any_kind_then_none(self):
        self.assertIsNone(pick_preview(self.node))
        (self.node / "shortcut.lnk").write_text("x", encoding="utf-8")
        (self.node / "meta.yaml").write_text("{}", encoding="utf-8")
        self.assertIsNone(pick_preview(self.node))

        write_image(self.node / "gen_b.png", 200)
        first = write_image(self.node / "Blackboard_a.png", 100)
        self.assertEqual(pick_preview(self.node), first)

    def test_index_refreshes_when_the_directory_changes(self):
        index = NodePreviewIndex()
        self.assertIsNone(index.preview_for(self.node))
        image = write_image(self.node / "a.png", 100)
        os.utime(self.node, (10_000, 10_000))
        self.assertEqual(index.preview_for(self.node), image)


class NodePreviewHttpTest(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.design = self.root / "design"

    def tearDown(self):
        self._tmp.cleanup()

    def test_lists_has_preview_and_serves_thumbnail_or_original(self):
        actions = self.design / "动作改2" / "new"
        with_image = write_node(actions / "a_with_image", "a_with_image")
        write_image(with_image / "comm_seed_1.png", 100)
        write_node(actions / "b_without_image", "b_without_image")
        thumbs = self.root / "thumbs"
        client = TestClient(create_app(
            node_workspace=NodeWorkspace(design_root=self.design),
            result_index=ResultIndex(roots=[], thumb_dir=thumbs),
        ))

        nodes = client.get("/api/nodes", params={"role": "action"}).json()["nodes"]
        self.assertEqual({node["name"]: node["has_preview"] for node in nodes}, {"a_with_image": True, "b_without_image": False})

        thumb = client.get("/api/nodes/preview-image", params={"ref": str(with_image), "size": 160})
        self.assertEqual(thumb.status_code, 200)
        self.assertEqual(thumb.headers["content-type"], "image/webp")
        original = client.get("/api/nodes/preview-image", params={"ref": str(with_image), "size": 0})
        self.assertEqual(original.headers["content-type"], "image/png")

        missing = client.get("/api/nodes/preview-image", params={"ref": str(actions / "b_without_image")})
        self.assertEqual(missing.status_code, 404)
        outside = client.get("/api/nodes/preview-image", params={"ref": str(self.root)})
        self.assertEqual(outside.status_code, 400)
        # 目录链接解析后落在 design_root 外的节点目录（/nodes/read 返回的就是这种路径）照样有预览。
        linked = write_node(self.root / "elsewhere" / "linked_node", "linked_node")
        write_image(linked / "comm_seed_9.png", 100)
        self.assertEqual(client.get("/api/nodes/preview-image", params={"ref": str(linked)}).status_code, 200)

    def test_pool_scan_reports_position_and_preview(self):
        actions = self.design / "动作改2" / "new"
        for index, name in enumerate(["n1", "n2", "n3"]):
            node = write_node(actions / name, name)
            if index != 1:
                write_image(node / "x.png", 100)
        config = self.root / "local.yaml"
        config.write_text(yaml.safe_dump({
            "legacy": {"tags_machine_root": str(self.root), "design_root": str(self.design)},
        }), encoding="utf-8")
        client = TestClient(create_app(config_path=config))

        response = client.post("/api/node-pools/scan", json={
            "role": "action",
            "spec": {"source": {"type": "folder", "value": "new"}},
            "q": "n3",
        })

        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        self.assertEqual([(item["name"], item["position"], item["has_preview"]) for item in items], [("n3", 2, True)])
