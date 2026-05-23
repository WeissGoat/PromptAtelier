import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tags_machine_core.cli import main


class CliNodesTest(unittest.TestCase):
    def _write_sample_nodes(self, root: Path) -> tuple[Path, Path]:
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
        return character, action

    def test_compose_nodes_command_filters_by_character_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_sample_nodes(root)

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

    def test_agent_task_and_compose_agent_nodes_reuse_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_sample_nodes(root)
            result = root / "agent_result.json"
            cache_dir = root / "cache"
            result.write_text(
                json.dumps(
                    {
                        "positive": "akemi homura, bare soles, foot focus",
                        "negative": "extra toes, face focus",
                        "character_scope": "foot_detail",
                        "included_character_sections": ["character", "feet"],
                        "suppressed_character_sections": ["eyes", "upper_clothes"],
                    }
                ),
                encoding="utf-8",
            )

            task_stdout = io.StringIO()
            with redirect_stdout(task_stdout):
                task_exit_code = main(
                    [
                        "agent-task-nodes",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--character-scope",
                        "foot_detail",
                        "--instruction",
                        "组合角色和动作，避免带入脸部细节",
                    ]
                )
            task_data = json.loads(task_stdout.getvalue())

            first_stdout = io.StringIO()
            with redirect_stdout(first_stdout):
                first_exit_code = main(
                    [
                        "compose-agent-nodes",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--character-scope",
                        "foot_detail",
                        "--instruction",
                        "组合角色和动作，避免带入脸部细节",
                        "--agent-result",
                        str(result),
                        "--cache-dir",
                        str(cache_dir),
                    ]
                )
            first_data = json.loads(first_stdout.getvalue())

            second_stdout = io.StringIO()
            with redirect_stdout(second_stdout):
                second_exit_code = main(
                    [
                        "compose-agent-nodes",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--character-scope",
                        "foot_detail",
                        "--instruction",
                        "组合角色和动作，避免带入脸部细节",
                        "--cache-dir",
                        str(cache_dir),
                    ]
                )
            second_data = json.loads(second_stdout.getvalue())

            self.assertEqual(task_exit_code, 0)
            self.assertEqual(first_exit_code, 0)
            self.assertEqual(second_exit_code, 0)
            self.assertEqual(task_data["schema"], "tags-machine-core.agent-composition-task/v1")
            self.assertEqual(first_data["cache"]["cache_key"], task_data["cache_key"])
            self.assertFalse(first_data["cache"]["cache_hit"])
            self.assertTrue(second_data["cache"]["cache_hit"])
            self.assertEqual(second_data["prompt"]["positive"], "akemi homura, bare soles, foot focus")
            self.assertEqual(second_data["meta"]["composer_type"], "agent")


if __name__ == "__main__":
    unittest.main()
