import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tags_machine_core.cli import main


class CliNodesTest(unittest.TestCase):
    def test_compose_nodes_command_filters_by_character_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character = root / "character"
            action = root / "action"
            character.mkdir()
            action.mkdir()
            (character / "meta.yaml").write_text(
                """
schema: tags-machine.character/v1
kind: character
id: homura
tags:
  character:
    - akemi homura
  eyes:
    - purple eyes
  upper_clothes:
    - school uniform
  feet:
    - bare soles
negative_prompt:
  - extra toes
""".strip(),
                encoding="utf-8",
            )
            (action / "meta.yaml").write_text(
                """
schema: tags-machine.action/v1
kind: action
id: foot_closeup
tags:
  action:
    - foot focus
character_scope: foot_detail
""".strip(),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "compose-nodes",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                    ]
                )

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            composition = data["meta"]["composition"]
            self.assertEqual(composition["character_scope"], "foot_detail")
            self.assertEqual(composition["included_character_sections"], ["character", "feet"])
            self.assertEqual(
                composition["suppressed_character_sections"],
                ["eyes", "upper_clothes"],
            )
            self.assertIn("akemi homura", data["prompt"]["positive"])
            self.assertIn("bare soles", data["prompt"]["positive"])
            self.assertIn("foot focus", data["prompt"]["positive"])
            self.assertNotIn("purple eyes", data["prompt"]["positive"])
            self.assertNotIn("school uniform", data["prompt"]["positive"])
            self.assertIn("extra toes", data["prompt"]["negative"])


if __name__ == "__main__":
    unittest.main()
