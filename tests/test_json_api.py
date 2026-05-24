import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tags_machine_core.cli import main
from tags_machine_core.services import GenerationJsonApi


def _write_sample_nodes(root: Path) -> tuple[Path, Path, Path]:
    character = root / "character"
    action = root / "action"
    style = root / "style"
    character.mkdir()
    action.mkdir()
    style.mkdir()
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
    (style / "node.yaml").write_text(
        """
schema: tags-machine.style/v1
kind: style
id: api_style
tags:
  style:
    - anime style
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
      steps: 30
  comfyui:
    workflow: portrait_workflow
    checkpoint: anime_comfy.safetensors
    params:
      steps: 32
      cfg: 6.5
""".strip(),
        encoding="utf-8",
    )
    return character, action, style


class JsonApiTest(unittest.TestCase):
    def test_compose_render_plan_json_api_roundtrip_from_node_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)

            result = GenerationJsonApi().compose_render_plan(
                {
                    "compose": {
                        "nodes": {
                            "character": str(character),
                            "action": str(action),
                        },
                        "style": str(style),
                    },
                    "render": {
                        "backend": "novelai",
                        "style": str(style),
                        "seed": 123,
                        "width": 832,
                        "height": 1216,
                    },
                }
            )

            bundle = result["prompt_bundle"]
            request = result["render_request"]
            self.assertEqual(result["schema"], "tags-machine-core.compose-render-plan-result/v1")
            self.assertEqual(bundle["meta"]["character_ref"], "homura")
            self.assertEqual(bundle["meta"]["action_ref"], "foot_closeup")
            self.assertEqual(bundle["meta"]["style_ref"], "api_style")
            self.assertEqual(bundle["meta"]["composition"]["character_scope"], "foot_detail")
            self.assertIn("akemi homura", bundle["prompt"]["positive"])
            self.assertIn("bare soles", bundle["prompt"]["positive"])
            self.assertNotIn("purple eyes", bundle["prompt"]["positive"])
            self.assertEqual(request["backend"], "novelai")
            self.assertEqual(request["seed"], 123)
            self.assertEqual(request["size"], {"width": 832, "height": 1216})
            self.assertEqual(request["params"]["steps"], 30)
            self.assertIn("style prefix", request["prompt"])
            self.assertIn("style suffix", request["prompt"])
            self.assertIn("bad anatomy", request["negative_prompt"])

    def test_render_plan_json_api_accepts_existing_prompt_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            api = GenerationJsonApi()
            bundle = api.compose(
                {
                    "nodes": {
                        "character": str(character),
                        "action": str(action),
                    },
                    "style": str(style),
                }
            )

            request = api.render_plan(
                {
                    "prompt_bundle": bundle,
                    "backend": "comfyui",
                    "style": str(style),
                    "seed": 456,
                    "params": {"scheduler": "karras"},
                }
            )

            self.assertEqual(request["backend"], "comfyui")
            self.assertEqual(request["model"], "anime_comfy.safetensors")
            self.assertEqual(request["seed"], 456)
            self.assertEqual(request["params"]["workflow"], "portrait_workflow")
            self.assertEqual(request["params"]["scheduler"], "karras")
            self.assertEqual(request["params"]["positive_prompt"], bundle["prompt"]["positive"])

    def test_cli_api_compose_render_plan_reads_json_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            request = root / "api_request.json"
            output = root / "api_response.json"
            request.write_text(
                json.dumps(
                    {
                        "compose": {
                            "nodes": {
                                "character": str(character),
                                "action": str(action),
                            },
                            "style": str(style),
                        },
                        "render": {
                            "backend": "comfyui",
                            "style": str(style),
                            "seed": 789,
                            "params": {"scheduler": "normal"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "api-compose-render-plan",
                        str(request),
                        "--output",
                        str(output),
                    ]
                )
            printed = json.loads(stdout.getvalue())
            written = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertTrue(output.exists())
            self.assertEqual(printed["render_request"]["backend"], "comfyui")
            self.assertEqual(written["render_request"]["seed"], 789)
            self.assertEqual(written["render_request"]["params"]["scheduler"], "normal")
            self.assertEqual(
                written["prompt_bundle"]["meta"]["composition"]["suppressed_character_sections"],
                ["eyes", "upper_clothes"],
            )


if __name__ == "__main__":
    unittest.main()
