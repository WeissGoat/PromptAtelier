import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tags_machine_core.cli import main


class CliNodesTest(unittest.TestCase):
    def test_compose_nodes_command_filters_by_action_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character = root / "character"
            action = root / "action"
            character.mkdir()
            action.mkdir()
            (character / "node.yaml").write_text(
                """
schema: tags-machine-core.node/v1
kind: character
id: homura
prompt:
  positive:
    - text: akemi homura
      include_scopes: ["*"]
    - text: purple eyes
      exclude_scopes: [foot_detail]
    - text: bare soles
      include_scopes: [foot_detail]
""".strip(),
                encoding="utf-8",
            )
            (action / "node.yaml").write_text(
                """
schema: tags-machine-core.node/v1
kind: action
id: foot_closeup
shot:
  body_scope: foot_detail
prompt:
  positive:
    - foot focus
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
            self.assertEqual(data["meta"]["shot"]["body_scope"], "foot_detail")
            self.assertIn("akemi homura", data["prompt"]["positive"])
            self.assertIn("bare soles", data["prompt"]["positive"])
            self.assertIn("foot focus", data["prompt"]["positive"])
            self.assertNotIn("purple eyes", data["prompt"]["positive"])


if __name__ == "__main__":
    unittest.main()
