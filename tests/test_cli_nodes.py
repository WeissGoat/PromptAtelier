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

    def _write_style_node(self, root: Path) -> Path:
        style = root / "style"
        style.mkdir()
        (style / "node.yaml").write_text(
            """
schema: tags-machine.style/v1
kind: style
id: cross_backend_style
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
      - style prefix
    prompt_suffix:
      - style suffix
    negative_prompt:
      - bad anatomy
    params:
      sampler: k_euler_ancestral
      noise_schedule: karras
      steps: 30
      reference_image_multiple:
        - abc
      reference_strength_multiple:
        - 0.25
  comfyui:
    workflow: portrait_workflow
    checkpoint: anime_comfy.safetensors
    loras:
      - name: lineart
        weight: 0.65
    params:
      steps: 32
      cfg: 6.5
  sd:
    checkpoint: anime_sd.safetensors
    vae: anime.vae.pt
    loras:
      - name: feet_detail
        weight: 0.8
    params:
      steps: 24
      cfg_scale: 7.5
""".strip(),
            encoding="utf-8",
        )
        return style

    def _write_background_node(self, root: Path) -> Path:
        background = root / "background"
        background.mkdir()
        (background / "meta.yaml").write_text(
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
        return background

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

    def test_compose_nodes_command_merges_background_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_sample_nodes(root)
            background = self._write_background_node(root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "compose-nodes",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--background",
                        str(background),
                    ]
                )

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["meta"]["background_ref"], "simple_room")
            self.assertIn("simple room", data["prompt"]["positive"])
            self.assertIn("soft window light", data["prompt"]["positive"])
            self.assertIn("crowded background", data["prompt"]["negative"])

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

    def test_render_plan_nodes_supports_comfyui_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_sample_nodes(root)
            style = self._write_style_node(root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "render-plan-nodes",
                        "--backend",
                        "comfyui",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--style-node",
                        str(style),
                        "--seed",
                        "123",
                        "--width",
                        "832",
                        "--height",
                        "1216",
                        "--params-json",
                        '{"scheduler": "karras"}',
                    ]
                )

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["backend"], "comfyui")
            self.assertEqual(data["model"], "anime_comfy.safetensors")
            self.assertEqual(data["seed"], 123)
            self.assertEqual(data["size"], {"width": 832, "height": 1216})
            self.assertEqual(data["params"]["workflow"], "portrait_workflow")
            self.assertEqual(data["params"]["steps"], 32)
            self.assertEqual(data["params"]["cfg"], 6.5)
            self.assertEqual(data["params"]["scheduler"], "karras")
            self.assertEqual(data["meta"]["style_ref"], "cross_backend_style")

    def test_render_plan_nodes_supports_novelai_structured_style_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_sample_nodes(root)
            style = self._write_style_node(root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "render-plan-nodes",
                        "--backend",
                        "novelai",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--style-node",
                        str(style),
                        "--seed",
                        "789",
                    ]
                )

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["backend"], "novelai")
            self.assertEqual(data["seed"], 789)
            self.assertEqual(data["params"]["steps"], 30)
            self.assertEqual(data["params"]["reference_image_multiple"], ["abc"])
            self.assertEqual(data["params"]["reference_strength_multiple"], [0.25])
            self.assertIn("style prefix", data["prompt"])
            self.assertIn("akemi homura", data["prompt"])
            self.assertIn("anime style", data["prompt"])
            self.assertIn("{best quality}", data["prompt"])
            self.assertIn("style suffix", data["prompt"])
            self.assertIn("extra toes", data["negative_prompt"])
            self.assertIn("lowres", data["negative_prompt"])
            self.assertIn("bad anatomy", data["negative_prompt"])
            self.assertEqual(data["meta"]["style_ref"], "cross_backend_style")

    def test_render_plan_nodes_supports_sd_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_sample_nodes(root)
            style = self._write_style_node(root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "render-plan-nodes",
                        "--backend",
                        "sd",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--style-node",
                        str(style),
                        "--seed",
                        "456",
                        "--model",
                        "override_sd.safetensors",
                        "--params-json",
                        '{"sampler": "DPM++ 2M", "clip_skip": 2}',
                    ]
                )

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["backend"], "sd")
            self.assertEqual(data["model"], "override_sd.safetensors")
            self.assertEqual(data["seed"], 456)
            self.assertEqual(data["params"]["checkpoint"], "override_sd.safetensors")
            self.assertEqual(data["params"]["steps"], 24)
            self.assertEqual(data["params"]["cfg_scale"], 7.5)
            self.assertEqual(data["params"]["sampler"], "DPM++ 2M")
            self.assertEqual(data["params"]["clip_skip"], 2)
            self.assertEqual(data["params"]["vae"], "anime.vae.pt")
            self.assertEqual(data["meta"]["style_ref"], "cross_backend_style")


if __name__ == "__main__":
    unittest.main()
