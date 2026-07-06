import tempfile
import unittest
from pathlib import Path

from tags_machine_core.nodes.reader import NodeReader


class CharacterIdentityMinimalTest(unittest.TestCase):
    def test_read_character_identity_minimal(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "homura"
            node_dir.mkdir()
            (node_dir / "meta.yaml").write_text(
                """
schema: tags-machine.character/v1
kind: character
id: homura
identity_minimal:
  - character
  - copyright
relations:
  cp:
    - kaname_madoka
tags:
  character:
    - akemi_homura
  copyright:
    - mahou_shoujo_madoka_magica
  role:
    - magical_girl
""".strip(),
                encoding="utf-8",
            )

            node = NodeReader().read(node_dir)

            self.assertEqual(node.identity_minimal, ["character", "copyright"])
            self.assertEqual(node.relations, {"cp": ["kaname_madoka"]})


if __name__ == "__main__":
    unittest.main()
