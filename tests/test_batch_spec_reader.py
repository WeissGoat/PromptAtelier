import unittest
from pathlib import Path
import tempfile

from tags_machine_core.batch.spec_reader import load_batch_spec


class BatchSpecReaderTest(unittest.TestCase):
    def test_batch_shorthand_maps_character_prompts_and_add_male_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_file = root / "batch.yaml"
            spec_file.write_text(
                """
name: test_shorthand
batch:
  composer: script
  character_prompts: false
  add_male_caption: false
""".strip(),
                encoding="utf-8",
            )
            spec = load_batch_spec(spec_file)
            self.assertIs(spec.defaults.character_prompts, False)
            self.assertIs(spec.defaults.add_male_caption, False)

    def test_batch_shorthand_character_prompts_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_file = root / "batch.yaml"
            spec_file.write_text(
                """
name: test_shorthand_auto
batch:
  composer: script
  character_prompts: auto
""".strip(),
                encoding="utf-8",
            )
            spec = load_batch_spec(spec_file)
            self.assertEqual(spec.defaults.character_prompts, "auto")


if __name__ == "__main__":
    unittest.main()
