import tempfile
import unittest
from pathlib import Path

from tags_machine_core.nodes import NodeReader


class NodeReaderTest(unittest.TestCase):
    def test_read_tags_txt_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "sample_node"
            node_dir.mkdir()
            (node_dir / "tags.txt").write_text("tag one\n# comment\ntag two\n", encoding="utf-8")

            node = NodeReader().read(node_dir)
            self.assertEqual(node.id, "sample_node")
            self.assertEqual(node.tags["legacy"], ["tag one", "tag two"])
            self.assertEqual(node.positive_texts(), ["tag one", "tag two"])

    def test_read_node_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "style_node"
            node_dir.mkdir()
            (node_dir / "node.yaml").write_text(
                """
schema: tags-machine.node/v1
kind: artist
id: style_node
tags:
  semantic:
    - watercolor
renderers:
  novelai:
    params:
      sampler: k_euler_ancestral
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)
            self.assertEqual(node.kind, "artist")
            self.assertEqual(node.tags["semantic"], ["watercolor"])
            self.assertIn("novelai", node.renderers)

    def test_read_style_node_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "anime_comfy"
            node_dir.mkdir()
            (node_dir / "node.yaml").write_text(
                """
schema: tags-machine.style/v1
kind: style
id: anime_comfy
tags:
  style:
    - anime style
  quality:
    - "{best quality}"
negative_prompt:
  - lowres
renderers:
  novelai:
    prompt_prefix:
      - "{best quality}"
    params:
      sampler: k_euler_ancestral
  comfyui:
    workflow: portrait_workflow
  sd:
    checkpoint: anime_sd.safetensors
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)
            self.assertEqual(node.kind, "style")
            self.assertEqual(node.tags["style"], ["anime style"])
            self.assertEqual(node.negative_prompt, ["lowres"])
            self.assertEqual(node.renderers["comfyui"]["workflow"], "portrait_workflow")

    def test_read_background_node_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "simple_room"
            node_dir.mkdir()
            (node_dir / "meta.yaml").write_text(
                """
schema: tags-machine.background/v1
kind: background
id: simple_room
tags:
  background:
    - simple room
  lighting:
    - soft window light
negative_prompt:
  - crowded background
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)
            self.assertEqual(node.kind, "background")
            self.assertEqual(node.tags["background"], ["simple room"])
            self.assertEqual(node.tags["lighting"], ["soft window light"])
            self.assertEqual(node.negative_prompt, ["crowded background"])

    def test_read_scoped_prompt_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "character_node"
            node_dir.mkdir()
            (node_dir / "node.yaml").write_text(
                """
schema: tags-machine-core.node/v1
kind: character
id: character_node
prompt:
  positive:
    - text: akemi homura
      role: identity
      include_scopes: ["*"]
    - text: purple eyes
      role: eyes
      exclude_scopes: [foot_detail]
    - text: bare soles
      role: feet
      include_scopes: [foot_detail]
  negative:
    - text: extra toes
      role: anatomy
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)
            self.assertEqual(node.positive_texts("foot_detail"), ["akemi homura", "bare soles"])
            self.assertEqual(
                node.positive_texts("face_detail"),
                ["akemi homura", "purple eyes"],
            )
            self.assertEqual(node.negative_texts("foot_detail"), ["extra toes"])


if __name__ == "__main__":
    unittest.main()
