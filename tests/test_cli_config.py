import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tags_machine_core.cli import _batch_config_path


class CliConfigTest(unittest.TestCase):
    def test_batch_config_prefers_local_yaml_when_spec_points_to_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configs = root / "configs"
            configs.mkdir()
            example = configs / "local.example.yaml"
            local = configs / "local.yaml"
            example.write_text("example: true\n", encoding="utf-8")
            local.write_text("local: true\n", encoding="utf-8")
            spec = SimpleNamespace(config=str(example))

            path = _batch_config_path(spec, spec_path=root / "batch.yaml", override=None)

            self.assertEqual(path, local)

    def test_batch_config_uses_example_when_local_yaml_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configs = root / "configs"
            configs.mkdir()
            example = configs / "local.example.yaml"
            example.write_text("example: true\n", encoding="utf-8")
            spec = SimpleNamespace(config=str(example))

            path = _batch_config_path(spec, spec_path=root / "batch.yaml", override=None)

            self.assertEqual(path, example)

    def test_batch_config_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = SimpleNamespace(config="configs/local.example.yaml")

            path = _batch_config_path(
                spec,
                spec_path=root / "batch.yaml",
                override=str(root / "custom.yaml"),
            )

            self.assertEqual(path, root / "custom.yaml")


if __name__ == "__main__":
    unittest.main()
