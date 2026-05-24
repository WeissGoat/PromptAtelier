import tempfile
import unittest
from pathlib import Path

import yaml

from tags_machine_core.nodes import (
    NodeReader,
    migrate_legacy_background_tags,
    migrate_legacy_style_tags,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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

    def test_migrate_legacy_style_tags_txt_to_style_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            style_dir = Path(tmp) / "old_style"
            style_dir.mkdir()
            (style_dir / "tags.txt").write_text(
                """
style prefix,
style suffix, best quality
=
origin_uc, lowres, bad anatomy
after_uc, extra fingers
gen_json, {"sampler": "k_euler_ancestral", "steps": 28, "reference_image_multiple": ["abc"], "reference_strength_multiple": [0.2]}
not_quality_prompts
""".strip(),
                encoding="utf-8",
            )

            node = migrate_legacy_style_tags(style_dir, node_id="migrated_style")

            self.assertEqual(node["schema"], "tags-machine.style/v1")
            self.assertEqual(node["kind"], "style")
            self.assertEqual(node["id"], "migrated_style")
            self.assertEqual(node["tags"]["style"], ["style prefix", "style suffix, best quality"])
            novelai = node["renderers"]["novelai"]
            self.assertFalse(novelai["include_common_tags"])
            self.assertEqual(novelai["prompt_prefix"], ["style prefix"])
            self.assertEqual(novelai["prompt_suffix"], ["style suffix, best quality"])
            self.assertEqual(novelai["negative_prompt"], ["lowres, bad anatomy"])
            self.assertEqual(novelai["after_negative_prompt"], ["extra fingers"])
            self.assertEqual(novelai["params"]["reference_image_multiple"], ["abc"])
            self.assertEqual(novelai["params"]["reference_strength_multiple"], [0.2])
            self.assertEqual(novelai["flags"], ["not_quality_prompts"])

    def test_migrate_legacy_background_tags_txt_to_background_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            background_dir = Path(tmp) / "old_background"
            background_dir.mkdir()
            (background_dir / "tags.txt").write_text(
                """
simple room,
wooden floor
=
origin_uc, crowded background
after_uc, messy room
gen_json, {"sampler": "ignored_for_background"}
""".strip(),
                encoding="utf-8",
            )

            node = migrate_legacy_background_tags(
                background_dir,
                node_id="migrated_background",
            )

            self.assertEqual(node["schema"], "tags-machine.background/v1")
            self.assertEqual(node["kind"], "background")
            self.assertEqual(node["id"], "migrated_background")
            self.assertEqual(node["tags"]["background"], ["simple room", "wooden floor"])
            self.assertEqual(node["negative_prompt"], ["crowded background", "messy room"])
            self.assertNotIn("renderers", node)

    def test_read_migrated_background_meta_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            background_dir = Path(tmp) / "old_background"
            background_dir.mkdir()
            (background_dir / "tags.txt").write_text(
                """
simple room,
=
uc, crowded background
""".strip(),
                encoding="utf-8",
            )
            output = background_dir / "meta.yaml"
            output.write_text(
                yaml.safe_dump(
                    migrate_legacy_background_tags(background_dir),
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            node = NodeReader().read(background_dir)

            self.assertEqual(node.kind, "background")
            self.assertEqual(node.id, "old_background")
            self.assertEqual(node.tags["background"], ["simple room"])
            self.assertEqual(node.negative_prompt, ["crowded background"])
            self.assertEqual(node.renderers, {})

    def test_read_migrated_style_node_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            style_dir = Path(tmp) / "old_style"
            style_dir.mkdir()
            (style_dir / "tags.txt").write_text(
                """
style prefix,
=
origin_uc, lowres
gen_json, {"sampler": "k_euler"}
""".strip(),
                encoding="utf-8",
            )
            output = style_dir / "node.yaml"
            output.write_text(
                yaml.safe_dump(
                    migrate_legacy_style_tags(style_dir),
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            node = NodeReader().read(style_dir)

            self.assertEqual(node.kind, "style")
            self.assertEqual(node.id, "old_style")
            self.assertEqual(node.tags["style"], ["style prefix"])
            self.assertEqual(node.renderers["novelai"]["negative_prompt"], ["lowres"])
            self.assertEqual(node.renderers["novelai"]["params"]["sampler"], "k_euler")

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

    def test_node_yaml_ignores_non_v1_shot_and_constraints_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "action_node"
            node_dir.mkdir()
            (node_dir / "meta.yaml").write_text(
                """
schema: tags-machine.action/v1
kind: action
id: action_node
tags:
  action:
    - foot focus
shot:
  body_scope: foot_detail
constraints:
  forbidden_parts:
    - eyes
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)
            payload = node.model_dump(mode="json", by_alias=True)

            self.assertEqual(node.kind, "action")
            self.assertEqual(node.character_scope, None)
            self.assertNotIn("shot", payload)
            self.assertNotIn("constraints", payload)

    def test_example_nodes_follow_v1_yaml_scope_contract(self):
        examples_root = PROJECT_ROOT / "examples" / "nodes"
        forbidden_keys_by_kind = {
            "character": {
                "rules",
                "profiles",
                "include_scopes",
                "exclude_scopes",
                "shot",
                "constraints",
            },
            "action": {
                "rules",
                "profiles",
                "include_scopes",
                "exclude_scopes",
                "shot",
                "constraints",
                "pose",
                "camera",
                "focus",
            },
            "background": {
                "rules",
                "profiles",
                "include_scopes",
                "exclude_scopes",
                "shot",
                "constraints",
                "renderers",
            },
            "style": {
                "rules",
                "profiles",
                "include_scopes",
                "exclude_scopes",
                "shot",
                "constraints",
            },
        }
        expected_file_by_kind = {
            "character": "meta.yaml",
            "action": "meta.yaml",
            "background": "meta.yaml",
            "style": "node.yaml",
        }
        violations: list[str] = []
        yaml_paths = sorted(examples_root.rglob("*.yaml"))

        for path in yaml_paths:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: expected YAML mapping")
                continue

            kind = str(data.get("kind") or "").strip()
            relative = path.relative_to(PROJECT_ROOT)
            expected_file = expected_file_by_kind.get(kind)
            if expected_file and path.name != expected_file:
                violations.append(f"{relative}: {kind} node should use {expected_file}")

            forbidden_keys = forbidden_keys_by_kind.get(kind, set())
            for key_path in _forbidden_yaml_key_paths(data, forbidden_keys):
                violations.append(f"{relative}: forbidden v1 field {key_path}")

            if kind == "action" and not str(data.get("character_scope") or "").strip():
                violations.append(f"{relative}: action node missing character_scope")
            if kind == "style":
                renderers = data.get("renderers")
                if not isinstance(renderers, dict) or not isinstance(renderers.get("novelai"), dict):
                    violations.append(f"{relative}: style node missing renderers.novelai")

        self.assertEqual(violations, [])


def _forbidden_yaml_key_paths(value, forbidden_keys: set[str], prefix: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            key_path = f"{prefix}.{key_text}"
            if key_text in forbidden_keys:
                paths.append(key_path)
            paths.extend(_forbidden_yaml_key_paths(item, forbidden_keys, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_forbidden_yaml_key_paths(item, forbidden_keys, f"{prefix}[{index}]"))
    return paths


if __name__ == "__main__":
    unittest.main()
