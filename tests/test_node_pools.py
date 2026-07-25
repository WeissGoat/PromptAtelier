import random
import tempfile
from pathlib import Path
from unittest import TestCase

import yaml

from tags_machine_core.node_pools import NodePoolResolver, NodePoolSpec


class NodePoolTest(TestCase):
    def _node(self, root: Path, name: str, classify: dict | None = None) -> Path:
        path = root / name
        path.mkdir(parents=True)
        (path / "tags.txt").write_text(f"{name}, standing", encoding="utf-8")
        if classify is not None:
            (path / "classify.yaml").write_text(
                yaml.safe_dump(classify, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        return path

    def _resolver(self, root: Path, collections=None) -> NodePoolResolver:
        def loader(role: str, ref: str):
            path = Path(ref)
            if not path.exists():
                raise FileNotFoundError(ref)
            return {
                "node": {
                    "schema": "tags-machine-core.node/v1",
                    "kind": role,
                    "id": path.name,
                    "name": path.name,
                    "prompt": {"positive": [], "negative": []},
                }
            }

        return NodePoolResolver(
            design_root=root,
            collections=collections or {},
            node_loader=loader,
        )

    def test_folder_scan_does_not_require_classify_when_filter_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._node(root, "a")
            self._node(root, "b")

            result = self._resolver(root).scan(
                "action",
                NodePoolSpec.model_validate({"source": {"type": "folder", "value": "."}}),
            )

            self.assertEqual([item.name for item in result.candidates], ["a", "b"])
            self.assertEqual(result.stats.missing_classify, 0)

    def test_classify_filters_use_or_within_field_and_and_across_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._node(root, "foot", {
                "phase": "core",
                "species": "human",
                "cast": "1boy1girl",
                "domain": ["foot", "sex"],
                "subtype": {"foot": ["footjob", "sole_focus"]},
                "pose": ["sitting"],
                "environment": [],
                "tone": "normal",
                "flags": [],
                "clothing": "clothed",
            })
            self._node(root, "mouth", {
                "phase": "core",
                "species": "human",
                "cast": "1boy1girl",
                "domain": ["mouth"],
                "subtype": {"mouth": ["oral"]},
                "pose": [],
                "environment": [],
                "tone": "normal",
                "flags": [],
                "clothing": "nude",
            })
            self._node(root, "missing")
            spec = NodePoolSpec.model_validate({
                "source": {"type": "folder", "value": "."},
                "filters": {"classify": {
                    "domain": ["foot", "body"],
                    "subtype": ["sole_focus", "barefoot"],
                    "tone": ["normal", "affectionate"],
                }},
            })

            result = self._resolver(root).scan("action", spec)

            self.assertEqual([item.name for item in result.candidates], ["foot"])
            self.assertEqual(result.stats.missing_classify, 1)
            self.assertEqual(result.stats.classify_mismatch, 1)
            self.assertIn("sole_focus", result.facets["subtype"])

    def test_sample_avoids_repeats_until_pool_is_exhausted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._node(root, "a")
            self._node(root, "b")
            spec = NodePoolSpec.model_validate({"source": {"type": "folder", "value": "."}})

            result = self._resolver(root).sample("character", spec, 5, rng=random.Random(3))
            refs = [item.candidate.ref for item in result.items]

            self.assertEqual(len(set(refs[:2])), 2)
            self.assertNotEqual(refs[1], refs[2])
            self.assertNotEqual(refs[3], refs[4])

    def test_collection_can_expand_folder_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group = root / "group"
            self._node(group, "a")
            self._node(group, "b")
            resolver = self._resolver(root, {
                "actions": {
                    "sample": [{"selector": "folder", "root": str(group)}],
                }
            })

            result = resolver.scan(
                "action",
                NodePoolSpec.model_validate({"source": {"type": "collection", "value": "sample"}}),
            )

            self.assertEqual([item.name for item in result.candidates], ["a", "b"])

    def test_classify_filter_rejects_non_action_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._node(root, "a")
            spec = NodePoolSpec.model_validate({
                "source": {"type": "folder", "value": "."},
                "filters": {"classify": {"domain": ["foot"]}},
            })

            with self.assertRaisesRegex(ValueError, "only supported for action"):
                self._resolver(root).scan("character", spec)
