import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tags_machine_core.contracts import GenerationResult, RenderRequest
from tags_machine_core.cli import main
from tags_machine_core.services import GenerationJsonApi
from tags_machine_core.verification import build_acceptance_record


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


def _write_config(root: Path) -> Path:
    legacy_root = root / "legacy"
    design_root = legacy_root / "design"
    output_dir = root / "outputs"
    design_root.mkdir(parents=True)
    config = root / "config.yaml"
    config.write_text(
        f"""
legacy:
  tags_machine_root: "{legacy_root.as_posix()}"
  design_root: "{design_root.as_posix()}"
runtime:
  output_dir: "{output_dir.as_posix()}"
novelai:
  base_url: "http://novelai.local"
  access_token_env: "NAI_ACCESS_TOKEN"
  timeout: 30
  retry: 1
""".strip(),
        encoding="utf-8",
    )
    return config


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

    def test_cli_api_compose_render_plan_matches_node_cli_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            request = root / "api_request.json"
            request.write_text(
                json.dumps(
                    {
                        "compose": {
                            "nodes": {
                                "character": str(character),
                                "action": str(action),
                            },
                            "style": str(style),
                            "extra_prompt": "dynamic low angle",
                            "negative": "messy crop",
                        },
                        "render": {
                            "backend": "novelai",
                            "style": str(style),
                            "seed": 1357,
                            "width": 832,
                            "height": 1216,
                            "params": {
                                "scale": 6.0,
                                "cfg_rescale": 0.15,
                                "reference_image_multiple": ["base64-reference"],
                                "reference_strength_multiple": [0.2],
                                "reference_information_extracted_multiple": [1.0],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            compose_stdout = io.StringIO()
            with redirect_stdout(compose_stdout):
                compose_exit = main(
                    [
                        "compose-nodes",
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--style-ref",
                        "api_style",
                        "--extra-prompt",
                        "dynamic low angle",
                        "--negative",
                        "messy crop",
                    ]
                )

            render_stdout = io.StringIO()
            with redirect_stdout(render_stdout):
                render_exit = main(
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
                        "--extra-prompt",
                        "dynamic low angle",
                        "--negative",
                        "messy crop",
                        "--seed",
                        "1357",
                        "--width",
                        "832",
                        "--height",
                        "1216",
                        "--params-json",
                        (
                            '{"scale": 6.0, "cfg_rescale": 0.15, '
                            '"reference_image_multiple": ["base64-reference"], '
                            '"reference_strength_multiple": [0.2], '
                            '"reference_information_extracted_multiple": [1.0]}'
                        ),
                    ]
                )

            api_stdout = io.StringIO()
            with redirect_stdout(api_stdout):
                api_exit = main(["api-compose-render-plan", str(request), "--full"])

            prompt_bundle = json.loads(compose_stdout.getvalue())
            render_request = json.loads(render_stdout.getvalue())
            api_result = json.loads(api_stdout.getvalue())

            self.assertEqual(compose_exit, 0)
            self.assertEqual(render_exit, 0)
            self.assertEqual(api_exit, 0)
            self.assertEqual(
                _without_runtime_fields(api_result["prompt_bundle"]),
                _without_runtime_fields(prompt_bundle),
            )
            self.assertEqual(api_result["render_request"], render_request)
            self.assertEqual(
                api_result["prompt_bundle"]["meta"]["composition"]["character_scope"],
                "foot_detail",
            )
            self.assertEqual(
                api_result["render_request"]["params"]["reference_image_multiple"],
                ["base64-reference"],
            )
            self.assertEqual(api_result["render_request"]["params"]["cfg_rescale"], 0.15)

    def test_cli_api_compose_render_plan_matches_run_prompt_for_full_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, style = _write_sample_nodes(root)
            prompt = "akemi homura, bare soles, foot focus, soles toward viewer"
            request = root / "api_request.json"
            request.write_text(
                json.dumps(
                    {
                        "compose": {
                            "prompt": prompt,
                            "negative": "bad feet",
                            "style": str(style),
                        },
                        "render": {
                            "backend": "novelai",
                            "style": str(style),
                            "seed": 2468,
                            "width": 832,
                            "height": 1216,
                            "params": {
                                "n_samples": 2,
                                "scale": 6.0,
                                "cfg_rescale": 0.15,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            run_prompt_stdout = io.StringIO()
            with redirect_stdout(run_prompt_stdout):
                run_prompt_exit = main(
                    [
                        "run-prompt",
                        "--dry-run",
                        "--full",
                        "--prompt",
                        prompt,
                        "--negative",
                        "bad feet",
                        "--style-node",
                        str(style),
                        "--seed",
                        "2468",
                        "--width",
                        "832",
                        "--height",
                        "1216",
                        "--nt",
                        "2",
                        "--params-json",
                        '{"scale": 6.0, "cfg_rescale": 0.15}',
                    ]
                )

            api_stdout = io.StringIO()
            with redirect_stdout(api_stdout):
                api_exit = main(["api-compose-render-plan", str(request), "--full"])

            run_prompt = json.loads(run_prompt_stdout.getvalue())
            api_result = json.loads(api_stdout.getvalue())

            self.assertEqual(run_prompt_exit, 0)
            self.assertEqual(api_exit, 0)
            self.assertEqual(
                _without_runtime_fields(api_result["prompt_bundle"]),
                _without_runtime_fields(run_prompt["prompt_bundle"]),
            )
            self.assertEqual(api_result["render_request"], run_prompt["render_request"])
            self.assertEqual(api_result["prompt_bundle"]["meta"]["character_ref"], None)
            self.assertEqual(api_result["prompt_bundle"]["meta"]["action_ref"], None)
            self.assertEqual(
                api_result["prompt_bundle"]["meta"]["composition"]["included_character_sections"],
                [],
            )
            self.assertEqual(api_result["render_request"]["params"]["n_samples"], 2)
            self.assertEqual(api_result["render_request"]["params"]["cfg_rescale"], 0.15)

    def test_generate_json_api_uses_injected_executor(self):
        calls = []

        def executor(render_request: RenderRequest, request_data):
            calls.append((render_request, request_data))
            return GenerationResult(
                backend=render_request.backend,
                request_body={
                    "input": render_request.prompt,
                    "parameters": render_request.params,
                },
                png_info={"images": []},
            )

        request = {
            "render_request": {
                "backend": "novelai",
                "prompt": "akemi homura",
                "negative_prompt": "bad anatomy",
                "seed": 123,
                "params": {"steps": 30},
            },
            "queue": {"job_id": "job-1"},
        }

        result = GenerationJsonApi(generation_executor=executor).generate(request)

        self.assertEqual(result["schema"], "tags-machine-core.generation-result/v1")
        self.assertEqual(result["backend"], "novelai")
        self.assertEqual(result["request_body"]["input"], "akemi homura")
        self.assertEqual(result["request_body"]["parameters"]["steps"], 30)
        self.assertEqual(calls[0][0].prompt, "akemi homura")
        self.assertEqual(calls[0][1]["queue"]["job_id"], "job-1")

    def test_generate_json_api_requires_executor(self):
        with self.assertRaises(ValueError) as raised:
            GenerationJsonApi().generate(
                {
                    "render_request": {
                        "backend": "novelai",
                        "prompt": "akemi homura",
                    }
                }
            )

        self.assertIn("generation_executor", str(raised.exception))

    def test_json_api_roundtrip_from_node_refs_to_acceptance_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            generated_image = root / "generated.png"
            executor_calls = []

            def executor(render_request: RenderRequest, request_data):
                executor_calls.append((render_request, request_data))
                generated_image.write_bytes(b"mock-image")
                return GenerationResult(
                    backend=render_request.backend,
                    images=[
                        {
                            "path": generated_image,
                            "filename": generated_image.name,
                            "meta": {"source": "mock-json-api"},
                        }
                    ],
                    request_body={
                        "input": render_request.prompt,
                        "model": render_request.model,
                        "action": render_request.meta.get("action"),
                        "parameters": render_request.params,
                    },
                    png_info={"images": []},
                )

            api = GenerationJsonApi(generation_executor=executor)
            planned = api.compose_render_plan(
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
                        "params": {
                            "n_samples": 2,
                            "reference_image_multiple": ["base64-reference"],
                            "reference_strength_multiple": [0.2],
                            "reference_information_extracted_multiple": [1.0],
                        },
                    },
                }
            )
            generation = api.generate(
                {
                    "render_request": planned["render_request"],
                    "queue": {"job_id": "json-api-e2e"},
                }
            )

            bundle_path = root / "prompt_bundle.json"
            render_request_path = root / "render_request.json"
            generation_path = root / "generation_result.json"
            legacy_source_path = root / "legacy_oracle.json"
            bundle_path.write_text(
                json.dumps(planned["prompt_bundle"], ensure_ascii=False),
                encoding="utf-8",
            )
            render_request_path.write_text(
                json.dumps(planned["render_request"], ensure_ascii=False),
                encoding="utf-8",
            )
            generation_path.write_text(
                json.dumps(generation, ensure_ascii=False),
                encoding="utf-8",
            )
            legacy_source_path.write_text(
                json.dumps(
                    {
                        "input": planned["render_request"]["prompt"],
                        "model": planned["render_request"]["model"],
                        "action": planned["render_request"]["meta"]["action"],
                        "parameters": planned["render_request"]["params"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            record = build_acceptance_record(
                case_id="foot_detail_json_api_001",
                legacy_source=legacy_source_path,
                core_source=render_request_path,
                prompt_bundle=bundle_path,
                generation_result=generation_path,
            )

            self.assertEqual(executor_calls[0][0].prompt, planned["render_request"]["prompt"])
            self.assertEqual(executor_calls[0][1]["queue"]["job_id"], "json-api-e2e")
            self.assertEqual(generation["schema"], "tags-machine-core.generation-result/v1")
            self.assertEqual(generation["request_body"]["parameters"]["n_samples"], 2)
            self.assertEqual(record["result"], "pass")
            self.assertTrue(record["diff"]["normalized_equal"])
            self.assertEqual(record["generation_result_evidence"]["result"], "pass")
            self.assertEqual(record["composition"]["character_scope"], "foot_detail")
            self.assertIn("feet", record["composition"]["included_character_sections"])
            self.assertIn("eyes", record["composition"]["suppressed_character_sections"])
            self.assertIn("upper_clothes", record["composition"]["suppressed_character_sections"])
            self.assertIn(
                "reference_image_multiple",
                record["normalized"]["core"]["parameters"],
            )

    def test_cli_api_generate_executes_novelai_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _write_config(root)
            output_dir = root / "api_outputs"
            request = root / "api_generate.json"
            response = root / "api_generate_response.json"
            request.write_text(
                json.dumps(
                    {
                        "render_request": {
                            "backend": "novelai",
                            "prompt": "akemi homura",
                            "negative_prompt": "bad anatomy",
                            "seed": 123,
                            "params": {"steps": 30},
                        },
                        "output_dir": str(output_dir),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.dict("os.environ", {"NAI_ACCESS_TOKEN": "token"}),
                patch("tags_machine_core.cli.NovelAIClient") as client_cls,
            ):
                client = client_cls.return_value
                client.generate_images.return_value = [
                    SimpleNamespace(filename="nai_result", content=b"image-bytes")
                ]
                client.build_payload.return_value = {
                    "input": "akemi homura",
                    "parameters": {"steps": 30},
                }

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "api-generate",
                            str(request),
                            "--config",
                            str(config),
                            "--output",
                            str(response),
                        ]
                    )

            printed = json.loads(stdout.getvalue())
            written = json.loads(response.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            client_cls.assert_called_once_with(
                access_token="token",
                base_url="http://novelai.local",
                timeout=30,
                retry=1,
            )
            client.generate_images.assert_called_once()
            self.assertEqual(client.generate_images.call_args.args[0].prompt, "akemi homura")
            self.assertEqual(printed["schema"], "tags-machine-core.generation-result/v1")
            self.assertEqual(printed["backend"], "novelai")
            self.assertEqual(written["request_body"]["parameters"]["steps"], 30)
            saved_path = Path(written["images"][0]["path"])
            self.assertEqual(saved_path.parent, output_dir)
            self.assertEqual(saved_path.suffix, ".png")
            self.assertEqual(saved_path.read_bytes(), b"image-bytes")

    def test_cli_api_generate_rejects_non_novelai_backend_in_v1_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _write_config(root)
            request = root / "api_generate_comfyui.json"
            response = root / "api_generate_response.json"
            request.write_text(
                json.dumps(
                    {
                        "render_request": {
                            "backend": "comfyui",
                            "prompt": "akemi homura",
                            "negative_prompt": "bad anatomy",
                            "params": {"workflow": "portrait_workflow"},
                        }
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as raised:
                main(
                    [
                        "api-generate",
                        str(request),
                        "--config",
                        str(config),
                        "--output",
                        str(response),
                    ]
                )

            self.assertIn("only NovelAI", str(raised.exception))
            self.assertFalse(response.exists())


def _without_runtime_fields(value):
    if isinstance(value, dict):
        return {
            key: _without_runtime_fields(item)
            for key, item in value.items()
            if key != "created_at"
        }
    if isinstance(value, list):
        return [_without_runtime_fields(item) for item in value]
    return value


if __name__ == "__main__":
    unittest.main()
