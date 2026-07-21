import io
import json
import os
import re
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tags_machine_core.contracts import GenerationResult, RenderRequest
from tags_machine_core.cli import main
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.novelai_artist import NovelAIArtistRepository
from tags_machine_core.services import GenerationJsonApi
from tags_machine_core.services.json_api_models import BatchItemRequest
from tags_machine_core.verification import build_acceptance_record


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _project_cwd():
    previous = os.getcwd()
    os.chdir(PROJECT_ROOT)
    try:
        yield
    finally:
        os.chdir(previous)


def _load_example_request(name: str) -> dict:
    path = PROJECT_ROOT / "examples" / "requests" / name
    return json.loads(path.read_text(encoding="utf-8"))


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
schema: tags-machine.artist/v1
kind: artist
id: api_style
tags:
  artist:
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
    workflow_json:
      "1":
        class_type: CLIPTextEncode
        inputs:
          text: ""
          negative: ""
          width: 1024
          height: 1024
          seed: 0
    inputs:
      positive_prompt: "1.inputs.text"
      negative_prompt: "1.inputs.negative"
      width: "1.inputs.width"
      height: "1.inputs.height"
      seed: "1.inputs.seed"
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
    def test_batch_item_model_accepts_full_prompt_input(self):
        item = BatchItemRequest.model_validate(
            {
                "id": "case_001",
                "compose": {
                    "composer": "full",
                    "prompt": "akemi homura, foot focus",
                    "negative": "bad anatomy",
                },
                "render": {
                    "backend": "novelai",
                    "artist": "examples/nodes/artists/anime_comfy",
                    "seed": 123,
                },
                "output": {"dir": "outputs/case_001"},
            }
        )

        self.assertEqual(item.id, "case_001")
        self.assertEqual(item.compose["composer"], "full")
        self.assertEqual(item.render["backend"], "novelai")
        self.assertEqual(item.output.dir, "outputs/case_001")

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
                        "artist": str(style),
                    },
                    "render": {
                        "backend": "novelai",
                        "artist": str(style),
                        "seed": 123,
                        "width": 832,
                        "height": 1216,
                    },
                }
            )

            bundle = result["prompt_bundle"]
            request = result["render_request"]
            self.assertEqual(result["schema"], "tags-machine-core.compose-render-plan-result/v1")
            self.assertEqual(
                [(node["role"], node["id"]) for node in bundle["meta"]["nodes"]],
                [("character", "homura"), ("action", "foot_closeup"), ("artist", "api_style")],
            )
            self.assertEqual(bundle["meta"]["composition"]["character_scope"], "foot_detail")
            self.assertIn("2.0::akemi_homura::", bundle["prompt"]["positive"])
            self.assertIn("bare_soles", bundle["prompt"]["positive"])
            self.assertNotIn("purple eyes", bundle["prompt"]["positive"])
            self.assertEqual(request["backend"], "novelai")
            self.assertEqual(request["seed"], 123)
            self.assertEqual(request["size"], {"width": 832, "height": 1216})
            self.assertEqual(request["params"]["steps"], 30)
            self.assertIn("style prefix", request["prompt"])
            self.assertIn("style suffix", request["prompt"])
            self.assertIn("bad anatomy", request["negative_prompt"])

    def test_compose_render_plan_uses_artist_loader_for_bare_artist_ref(self):
        calls = []

        def load_artist(ref: str) -> NodeDocument:
            calls.append(ref)
            return NodeDocument(
                kind="artist",
                id=ref,
                name=ref,
                renderers={
                    "novelai": {
                        "prompt_prefix": ["artist prefix"],
                        "params": {"steps": 28},
                    }
                },
            )

        result = GenerationJsonApi(artist_loader=load_artist).compose_render_plan(
            {
                "compose": {
                    "prompt": "1girl, standing",
                },
                "render": {
                    "backend": "novelai",
                    "artist": "20260412",
                },
            }
        )

        self.assertEqual(calls, ["20260412", "20260412"])
        self.assertIn("artist prefix", result["render_request"]["prompt"])
        self.assertEqual(result["render_request"]["params"]["steps"], 28)

    def test_existing_absolute_artist_path_uses_artist_loader_before_node_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            artist_path = design_root / "legacy_artist"
            artist_path.mkdir(parents=True)
            (artist_path / "tags.txt").write_text(
                "absolute artist marker,\nquality suffix,",
                encoding="utf-8",
            )
            repository = NovelAIArtistRepository(design_root)
            calls: list[str] = []

            def load_artist(ref: str) -> NodeDocument:
                calls.append(ref)
                return repository.load_node(ref)

            node_reader = Mock()
            node_reader.read.side_effect = AssertionError("artist path must bypass NodeReader")
            result = GenerationJsonApi(
                artist_loader=load_artist,
                node_reader=node_reader,
            ).compose_render_plan(
                {
                    "compose": {"prompt": "1girl, standing"},
                    "render": {
                        "backend": "novelai",
                        "artist": artist_path,
                    },
                }
            )

            self.assertEqual(calls, [str(artist_path), str(artist_path)])
            node_reader.read.assert_not_called()
            self.assertEqual(
                result["render_request"]["prompt"].count("absolute artist marker"),
                1,
            )

    def test_inline_artist_mapping_bypasses_configured_artist_loader(self):
        artist_loader = Mock(side_effect=AssertionError("inline artist must not use loader"))
        result = GenerationJsonApi(artist_loader=artist_loader).compose_render_plan(
            {
                "compose": {"prompt": "1girl, standing"},
                "render": {
                    "backend": "novelai",
                    "artist": {
                        "kind": "artist",
                        "id": "inline-artist",
                        "renderers": {
                            "novelai": {
                                "prompt_prefix": ["inline artist marker"],
                            }
                        },
                    },
                },
            }
        )

        artist_loader.assert_not_called()
        self.assertEqual(
            result["render_request"]["prompt"].count("inline artist marker"),
            1,
        )

    def test_compose_render_plan_deduplicates_real_legacy_explicit_and_resolved_artist(self):
        with tempfile.TemporaryDirectory() as tmp:
            design_root = Path(tmp) / "design"
            artist_path = design_root / "legacy_artist"
            artist_path.mkdir(parents=True)
            (artist_path / "tags.txt").write_text(
                "real legacy artist marker,\nquality suffix,",
                encoding="utf-8",
            )
            repository = NovelAIArtistRepository(design_root)

            result = GenerationJsonApi(
                artist_loader=repository.load_node,
            ).compose_render_plan(
                {
                    "compose": {
                        "nodes": [
                            {"role": "artist", "ref": str(artist_path)},
                            {
                                "role": "character",
                                "ref": "inline-character",
                                "node": {
                                    "kind": "character",
                                    "id": "subject",
                                    "prompt": {"positive": ["1girl, standing"]},
                                },
                            },
                        ],
                    },
                    "render": {
                        "backend": "novelai",
                        "artist": str(artist_path),
                    },
                }
            )

            prompt = result["render_request"]["prompt"]
            self.assertEqual(prompt.count("real legacy artist marker"), 1)
            self.assertEqual(prompt.count("quality suffix"), 1)

    def test_compose_render_plan_json_api_supports_node_list_character_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, _ = _write_sample_nodes(root)
            second = root / "second_character"
            second.mkdir()
            (second / "meta.yaml").write_text(
                """
schema: tags-machine.character/v1
kind: character
id: madoka
tags:
  character:
    - kaname madoka
  hair:
    - pink hair
""".strip(),
                encoding="utf-8",
            )

            result = GenerationJsonApi().compose_render_plan(
                {
                    "compose": {
                        "nodes": [
                            {"role": "character", "ref": str(character)},
                            {"role": "character", "ref": str(second)},
                            {"role": "action", "ref": str(action)},
                        ],
                    },
                    "render": {
                        "backend": "novelai",
                        "model": "nai-diffusion-4-5-full",
                        "params": {"character_prompts": {"mode": "auto"}},
                    },
                }
            )

            caption = result["render_request"]["params"]["v4_prompt"]["caption"]
            self.assertEqual(len(caption["char_captions"]), 2)
            self.assertIn("2.0::akemi_homura::", caption["char_captions"][0]["char_caption"])
            self.assertIn("2.0::kaname_madoka::", caption["char_captions"][1]["char_caption"])
            self.assertNotIn("akemi homura", caption["base_caption"])

    def test_compose_render_plan_full_prompt_uses_nodes_only_as_render_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            prompt = "akemi homura, bare soles, foot focus, soles close-up"

            result = GenerationJsonApi().compose_render_plan(
                {
                    "compose": {
                        "prompt": prompt,
                        "nodes": {
                            "character": str(character),
                            "action": str(action),
                        },
                        "artist": str(style),
                    },
                    "render": {
                        "backend": "novelai",
                        "artist": str(style),
                        "model": "nai-diffusion-4-5-full",
                        "params": {"character_prompts": {"mode": "auto"}},
                    },
                }
            )

            bundle = result["prompt_bundle"]
            request = result["render_request"]
            caption = request["params"]["v4_prompt"]["caption"]
            char_caption = caption["char_captions"][0]["char_caption"]
            self.assertEqual(bundle["prompt"]["positive"], prompt)
            self.assertEqual(bundle["meta"]["nodes"], [])
            self.assertEqual(
                bundle["meta"]["composition"]["included_character_sections"],
                [],
            )
            self.assertNotIn("purple eyes", char_caption)
            self.assertIn("akemi homura", char_caption)
            self.assertIn("bare soles", char_caption)
            self.assertIn("foot focus", caption["base_caption"])
            self.assertNotIn("akemi homura", caption["base_caption"])
            self.assertEqual(request["meta"]["node_refs"][0]["id"], "homura")
            self.assertEqual(
                request["meta"]["character_materials"][0]["used_sections"],
                ["character", "eyes", "upper_clothes", "feet"],
            )

    def test_compose_json_api_supports_node_mapping_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, _ = _write_sample_nodes(root)
            second = root / "second_character"
            second.mkdir()
            (second / "meta.yaml").write_text(
                """
schema: tags-machine.character/v1
kind: character
id: madoka
tags:
  character:
    - kaname madoka
""".strip(),
                encoding="utf-8",
            )

            bundle = GenerationJsonApi().compose(
                {
                    "nodes": {
                        "character": [str(character), {"ref": str(second)}],
                        "action": str(action),
                    }
                }
            )

            self.assertEqual(bundle["meta"]["nodes"][0]["id"], "homura")
            self.assertEqual(bundle["meta"]["nodes"][1]["id"], "madoka")
            self.assertIn("2.0::kaname_madoka::", bundle["prompt"]["positive"])

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
                    "artist": str(style),
                }
            )

            request = api.render_plan(
                {
                    "prompt_bundle": bundle,
                    "backend": "comfyui",
                    "artist": str(style),
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

    def test_render_plan_json_api_rejects_unknown_backend_with_support_matrix_error(self):
        bundle = {
            "schema": "tags-machine-core.prompt-bundle/v2",
            "prompt": {
                "positive": "akemi homura",
                "negative": "",
            },
        }

        with self.assertRaises(ValueError) as raised:
            GenerationJsonApi().render_plan(
                {
                    "prompt_bundle": bundle,
                    "backend": "unknown",
                }
            )

        self.assertIn("Unsupported backend: unknown", str(raised.exception))
        self.assertIn("expected one of: novelai, comfyui, sd", str(raised.exception))

    def test_cli_api_compose_render_plan_rejects_unknown_backend_without_writing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / "api_request.json"
            output = root / "api_response.json"
            request.write_text(
                json.dumps(
                    {
                        "compose": {
                            "prompt": "akemi homura",
                        },
                        "render": {
                            "backend": "unknown",
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as raised:
                main(
                    [
                        "api-compose-render-plan",
                        str(request),
                        "--output",
                        str(output),
                    ]
                )

            self.assertIn("Unsupported backend: unknown", str(raised.exception))
            self.assertIn("expected one of: novelai, comfyui, sd", str(raised.exception))
            self.assertFalse(output.exists())

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
                            "artist": str(style),
                        },
                        "render": {
                            "backend": "comfyui",
                            "artist": str(style),
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
                            "artist": str(style),
                            "extra_prompt": "dynamic low angle",
                            "negative": "messy crop",
                        },
                        "render": {
                            "backend": "novelai",
                            "artist": str(style),
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
                        "--node",
                        f"artist:{style}",
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
                        "--artist-node",
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
            self.assertEqual(
                _without_trace_locations(api_result["render_request"]),
                _without_trace_locations(render_request),
            )
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
                            "artist": str(style),
                        },
                        "render": {
                            "backend": "novelai",
                            "artist": str(style),
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
                        "--artist-node",
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
            self.assertEqual(
                _without_trace_locations(api_result["render_request"]),
                _without_trace_locations(run_prompt["render_request"]),
            )
            self.assertEqual(api_result["prompt_bundle"]["meta"]["nodes"], [])
            self.assertEqual(
                api_result["prompt_bundle"]["meta"]["composition"]["included_character_sections"],
                [],
            )
            self.assertEqual(api_result["render_request"]["params"]["n_samples"], 2)
            self.assertEqual(api_result["render_request"]["params"]["cfg_rescale"], 0.15)

    def test_example_full_prompt_render_plan_matches_run_prompt(self):
        request_path = "examples\\requests\\full_prompt_render_plan_novelai.json"
        prompt = "akemi homura, bare soles, foot focus, soles toward viewer"
        with _project_cwd():
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
                        "--artist-node",
                        "examples\\nodes\\artists\\anime_comfy",
                        "--seed",
                        "123",
                        "--width",
                        "832",
                        "--height",
                        "1216",
                        "--nt",
                        "1",
                        "--params-json",
                        '{"cfg_rescale": 0.15}',
                    ]
                )

            api_stdout = io.StringIO()
            with redirect_stdout(api_stdout):
                api_exit = main(["api-compose-render-plan", request_path, "--full"])

        run_prompt = json.loads(run_prompt_stdout.getvalue())
        api_result = json.loads(api_stdout.getvalue())

        self.assertEqual(run_prompt_exit, 0)
        self.assertEqual(api_exit, 0)
        self.assertEqual(
            _without_runtime_fields(api_result["prompt_bundle"]),
            _without_runtime_fields(run_prompt["prompt_bundle"]),
        )
        self.assertEqual(
            _without_trace_locations(api_result["render_request"]),
            _without_trace_locations(run_prompt["render_request"]),
        )
        self.assertEqual(api_result["prompt_bundle"]["meta"]["nodes"], [])
        self.assertEqual(
            api_result["prompt_bundle"]["meta"]["composition"]["included_character_sections"],
            [],
        )
        self.assertEqual(
            api_result["prompt_bundle"]["meta"]["composition"]["suppressed_character_sections"],
            [],
        )

    def test_agent_json_api_builds_task_and_reuses_cached_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            cache_dir = root / "cache" / "prompt"
            request = {
                "nodes": {
                    "character": str(character),
                    "action": str(action),
                },
                "artist": str(style),
                "extra_prompt": "soles toward viewer",
                "negative": "face focus",
                "character_scope": "foot_detail",
                "agent": {
                    "model": "agent-model-v1",
                    "instructions": ["局部特写只保留脚部相关角色细节"],
                    "result": {
                        "positive": "akemi homura, bare soles, foot focus, soles toward viewer",
                        "negative": "extra toes, face focus",
                        "character_scope": "foot_detail",
                        "included_character_sections": ["character", "feet"],
                        "suppressed_character_sections": ["eyes", "upper_clothes"],
                        "notes": ["agent 已按 foot_detail 合并"],
                    },
                },
                "cache": {
                    "cache_dir": str(cache_dir),
                },
            }
            api = GenerationJsonApi()

            task = api.agent_task(request)
            first = api.compose_agent(request)
            second_request = dict(request)
            second_request["agent"] = {
                "model": "agent-model-v1",
                "instructions": ["局部特写只保留脚部相关角色细节"],
            }
            second = api.compose_agent(second_request)

            self.assertEqual(task["schema"], "tags-machine-core.agent-composition-task/v2")
            self.assertTrue(task["cache_key"].startswith("sha256:"))
            self.assertEqual(task["nodes"]["character"]["id"], "homura")
            self.assertEqual(task["nodes"]["action"]["node"]["character_scope"], "foot_detail")
            self.assertEqual(task["instructions"], ["局部特写只保留脚部相关角色细节"])
            self.assertEqual(task["agent_model"], "agent-model-v1")
            self.assertEqual(first["meta"]["composer_type"], "agent")
            artist_nodes = [node for node in first["meta"]["nodes"] if node["role"] == "artist"]
            self.assertEqual(artist_nodes[0]["id"], "api_style")
            self.assertEqual(first["meta"]["agent"]["agent_model"], "agent-model-v1")
            self.assertEqual(first["prompt"]["positive"], "akemi homura, bare soles, foot focus, soles toward viewer")
            self.assertEqual(first["meta"]["composition"]["suppressed_character_sections"], ["eyes", "upper_clothes"])
            self.assertFalse(first["cache"]["cache_hit"])
            self.assertTrue(second["cache"]["cache_hit"])
            self.assertEqual(
                _without_runtime_fields(first),
                _without_runtime_fields({**second, "cache": {**second["cache"], "cache_hit": False}}),
            )

    def test_agent_json_api_prompt_input_overwrites_cached_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            cache_dir = root / "cache" / "prompt"
            base_request = {
                "nodes": {
                    "character": str(character),
                    "action": str(action),
                },
                "artist": str(style),
                "agent": {
                    "model": "agent-model-v1",
                },
                "cache": {
                    "cache_dir": str(cache_dir),
                },
            }
            api = GenerationJsonApi()

            first = api.compose_agent(
                {
                    **base_request,
                    "prompt": "cached prompt",
                    "negative": "cached negative",
                }
            )
            second = api.compose_agent(
                {
                    **base_request,
                    "prompt": "fresh prompt",
                    "negative": "fresh negative",
                }
            )
            third = api.compose_agent(base_request)

            self.assertFalse(first["cache"]["cache_hit"])
            self.assertFalse(second["cache"]["cache_hit"])
            self.assertTrue(third["cache"]["cache_hit"])
            self.assertEqual(first["cache"]["cache_key"], second["cache"]["cache_key"])
            self.assertEqual(second["cache"]["cache_key"], third["cache"]["cache_key"])
            self.assertEqual(second["prompt"]["positive"], "fresh prompt")
            self.assertEqual(second["prompt"]["negative"], "fresh negative")
            self.assertEqual(third["prompt"]["positive"], "fresh prompt")
            self.assertEqual(third["prompt"]["negative"], "fresh negative")

    def test_agent_json_api_does_not_reuse_cache_when_agent_model_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            cache_dir = root / "cache" / "prompt"
            base_request = {
                "nodes": {
                    "character": str(character),
                    "action": str(action),
                },
                "artist": str(style),
                "extra_prompt": "soles toward viewer",
                "negative": "face focus",
                "character_scope": "foot_detail",
                "cache": {
                    "cache_dir": str(cache_dir),
                },
            }
            api = GenerationJsonApi()
            v1_request = {
                **base_request,
                "agent": {
                    "model": "agent-model-v1",
                    "instructions": ["局部特写只保留脚部相关角色细节"],
                    "result": {
                        "positive": "akemi homura, bare soles, foot focus, soles toward viewer",
                        "negative": "extra toes, face focus",
                        "character_scope": "foot_detail",
                        "included_character_sections": ["character", "feet"],
                        "suppressed_character_sections": ["eyes", "upper_clothes"],
                    },
                },
            }
            v2_request = {
                **base_request,
                "agent": {
                    "model": "agent-model-v2",
                    "instructions": ["局部特写只保留脚部相关角色细节"],
                },
            }

            ready = api.resolve_agent(v1_request)
            missing_v2 = api.resolve_agent(v2_request)

            self.assertEqual(ready["status"], "ready")
            self.assertEqual(missing_v2["status"], "requires_agent")
            self.assertEqual(missing_v2["agent_task"]["agent_model"], "agent-model-v2")
            self.assertNotEqual(
                ready["prompt_bundle"]["cache"]["cache_key"],
                missing_v2["agent_task"]["cache_key"],
            )

    def test_agent_json_api_accepts_agent_model_alias_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            base_request = {
                "nodes": {
                    "character": str(character),
                    "action": str(action),
                },
                "artist": str(style),
                "extra_prompt": "soles toward viewer",
                "negative": "face focus",
                "character_scope": "foot_detail",
            }
            result = {
                "positive": "akemi homura, bare soles, foot focus, soles toward viewer",
                "negative": "extra toes, face focus",
                "character_scope": "foot_detail",
                "included_character_sections": ["character", "feet"],
                "suppressed_character_sections": ["eyes", "upper_clothes"],
            }
            api = GenerationJsonApi()
            cases = [
                ("top_level_agent_model", {"agent_model": "agent-model-v1"}, {}),
                ("agent_agent_model", {}, {"agent_model": "agent-model-v1"}),
                ("agent_model", {}, {"model": "agent-model-v1"}),
                ("agent_model_version", {}, {"model_version": "agent-model-v1"}),
            ]
            cache_keys = set()

            for case_id, request_extra, agent_extra in cases:
                with self.subTest(case=case_id):
                    request = {
                        **base_request,
                        **request_extra,
                        "agent": {
                            "instructions": ["局部特写只保留脚部相关角色细节"],
                            "result": result,
                            **agent_extra,
                        },
                    }
                    task = api.agent_task(request)
                    bundle = api.compose_agent(request)

                    self.assertEqual(task["agent_model"], "agent-model-v1")
                    self.assertEqual(bundle["meta"]["agent"]["agent_model"], "agent-model-v1")
                    self.assertEqual(task["cache_key"], bundle["cache"]["cache_key"])
                    cache_keys.add(task["cache_key"])

            self.assertEqual(len(cache_keys), 1)

    def test_agent_json_api_accepts_cache_dir_alias_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            base_request = {
                "nodes": {
                    "character": str(character),
                    "action": str(action),
                },
                "artist": str(style),
                "extra_prompt": "soles toward viewer",
                "negative": "face focus",
                "character_scope": "foot_detail",
            }
            result = {
                "positive": "akemi homura, bare soles, foot focus, soles toward viewer",
                "negative": "extra toes, face focus",
                "character_scope": "foot_detail",
                "included_character_sections": ["character", "feet"],
                "suppressed_character_sections": ["eyes", "upper_clothes"],
            }
            api = GenerationJsonApi()
            cases = [
                ("top_level_cache_dir", {"cache_dir": str(root / "top-level")}, {}),
                ("top_level_cache_root", {"cache_root": str(root / "top-level-root")}, {}),
                ("agent_cache_dir", {}, {"cache_dir": str(root / "agent-level")}),
                ("agent_cache_root", {}, {"cache_root": str(root / "agent-level-root")}),
                ("cache_object_cache_root", {"cache": {"cache_root": str(root / "cache-object")}}, {}),
            ]

            for case_id, request_extra, agent_extra in cases:
                with self.subTest(case=case_id):
                    agent_base = {
                        "model": "agent-model-v1",
                        "instructions": ["局部特写只保留脚部相关角色细节"],
                        **agent_extra,
                    }
                    first = api.compose_agent(
                        {
                            **base_request,
                            **request_extra,
                            "agent": {
                                **agent_base,
                                "result": result,
                            },
                        }
                    )
                    second = api.compose_agent(
                        {
                            **base_request,
                            **request_extra,
                            "agent": agent_base,
                        }
                    )

                    self.assertFalse(first["cache"]["cache_hit"])
                    self.assertTrue(second["cache"]["cache_hit"])
                    self.assertEqual(first["cache"]["cache_key"], second["cache"]["cache_key"])
                    self.assertEqual(second["meta"]["agent"]["agent_model"], "agent-model-v1")

    def test_resolve_agent_json_api_returns_task_on_cache_miss_then_cached_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            cache_dir = root / "cache" / "prompt"
            request = {
                "nodes": {
                    "character": str(character),
                    "action": str(action),
                },
                "artist": str(style),
                "extra_prompt": "soles toward viewer",
                "negative": "face focus",
                "character_scope": "foot_detail",
                "agent": {
                    "instructions": ["局部特写只保留脚部相关角色细节"],
                },
                "cache": {
                    "cache_dir": str(cache_dir),
                },
            }
            api = GenerationJsonApi()

            missing = api.resolve_agent(request)
            with_result = {
                **request,
                "agent": {
                    "instructions": ["局部特写只保留脚部相关角色细节"],
                    "result": {
                        "positive": "akemi homura, bare soles, foot focus, soles toward viewer",
                        "negative": "extra toes, face focus",
                        "character_scope": "foot_detail",
                        "included_character_sections": ["character", "feet"],
                        "suppressed_character_sections": ["eyes", "upper_clothes"],
                    },
                },
            }
            created = api.resolve_agent(with_result)
            cached = api.resolve_agent(request)

            self.assertEqual(missing["schema"], "tags-machine-core.agent-compose-resolution/v1")
            self.assertEqual(missing["status"], "requires_agent")
            self.assertEqual(missing["agent_task"]["schema"], "tags-machine-core.agent-composition-task/v2")
            self.assertEqual(missing["agent_task"]["nodes"]["action"]["node"]["character_scope"], "foot_detail")
            self.assertEqual(created["status"], "ready")
            self.assertFalse(created["prompt_bundle"]["cache"]["cache_hit"])
            self.assertEqual(cached["status"], "ready")
            self.assertTrue(cached["prompt_bundle"]["cache"]["cache_hit"])
            self.assertEqual(
                missing["agent_task"]["cache_key"],
                created["prompt_bundle"]["cache"]["cache_key"],
            )
            self.assertEqual(
                _without_runtime_fields(created["prompt_bundle"]),
                _without_runtime_fields(
                    {
                        **cached["prompt_bundle"],
                        "cache": {**cached["prompt_bundle"]["cache"], "cache_hit": False},
                    }
                ),
            )

    def test_agent_compose_render_plan_json_api_builds_bundle_and_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            cache_dir = root / "cache" / "prompt"
            api = GenerationJsonApi()
            request = {
                "compose": {
                    "nodes": {
                        "character": str(character),
                        "action": str(action),
                    },
                    "artist": str(style),
                    "extra_prompt": "soles toward viewer",
                    "negative": "face focus",
                    "character_scope": "foot_detail",
                    "agent": {
                        "model": "agent-model-v1",
                        "instructions": ["局部特写只保留脚部相关角色细节"],
                        "result": {
                            "positive": "akemi homura, bare soles, foot focus, soles toward viewer",
                            "negative": "extra toes, face focus",
                            "character_scope": "foot_detail",
                            "included_character_sections": ["character", "feet"],
                            "suppressed_character_sections": ["eyes", "upper_clothes"],
                        },
                    },
                    "cache": {
                        "cache_dir": str(cache_dir),
                    },
                },
                "render": {
                    "backend": "novelai",
                    "artist": str(style),
                    "seed": 2468,
                    "width": 832,
                    "height": 1216,
                    "params": {
                        "n_samples": 2,
                        "scale": 6.0,
                    },
                },
            }

            first = api.compose_render_plan(request)
            second_request = {
                **request,
                "compose": {
                    **request["compose"],
                    "agent": {
                        "model": "agent-model-v1",
                        "instructions": ["局部特写只保留脚部相关角色细节"],
                    },
                },
            }
            second = api.compose_render_plan(second_request)

            first_bundle = first["prompt_bundle"]
            first_render = first["render_request"]
            second_bundle = second["prompt_bundle"]
            second_render = second["render_request"]

            self.assertEqual(first["schema"], "tags-machine-core.compose-render-plan-result/v1")
            self.assertEqual(first_bundle["meta"]["composer_type"], "agent")
            artist_nodes = [node for node in first_bundle["meta"]["nodes"] if node["role"] == "artist"]
            self.assertEqual(artist_nodes[0]["id"], "api_style")
            self.assertEqual(first_bundle["meta"]["agent"]["agent_model"], "agent-model-v1")
            self.assertEqual(first_bundle["meta"]["composition"]["character_scope"], "foot_detail")
            self.assertEqual(first_bundle["meta"]["composition"]["suppressed_character_sections"], ["eyes", "upper_clothes"])
            self.assertEqual(first_bundle["prompt"]["positive"], "akemi homura, bare soles, foot focus, soles toward viewer")
            self.assertFalse(first_bundle["cache"]["cache_hit"])
            self.assertTrue(second_bundle["cache"]["cache_hit"])
            self.assertEqual(first_render["backend"], "novelai")
            self.assertEqual(first_render["seed"], 2468)
            self.assertEqual(first_render["size"], {"width": 832, "height": 1216})
            self.assertEqual(first_render["params"]["n_samples"], 2)
            self.assertEqual(first_render["params"]["scale"], 6.0)
            self.assertEqual(first_render["meta"]["composer_type"], "agent")
            self.assertEqual(first_render["meta"]["prompt_cache_key"], first_bundle["cache"]["cache_key"])
            self.assertIn("style prefix", first_render["prompt"])
            self.assertIn("akemi homura, bare soles, foot focus, soles toward viewer", first_render["prompt"])
            self.assertIn("style suffix", first_render["prompt"])
            self.assertIn("bad anatomy", first_render["negative_prompt"])
            self.assertEqual(
                _without_runtime_fields(first_bundle),
                _without_runtime_fields({**second_bundle, "cache": {**second_bundle["cache"], "cache_hit": False}}),
            )
            self.assertEqual(first_render, second_render)

    def test_resolve_compose_render_plan_json_api_returns_task_or_ready_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            cache_dir = root / "cache" / "prompt"
            api = GenerationJsonApi()
            request = {
                "compose": {
                    "nodes": {
                        "character": str(character),
                        "action": str(action),
                    },
                    "artist": str(style),
                    "extra_prompt": "soles toward viewer",
                    "negative": "face focus",
                    "character_scope": "foot_detail",
                    "agent": {
                        "model": "agent-model-v1",
                        "instructions": ["局部特写只保留脚部相关角色细节"],
                    },
                    "cache": {
                        "cache_dir": str(cache_dir),
                    },
                },
                "render": {
                    "backend": "novelai",
                    "artist": str(style),
                    "seed": 2468,
                    "width": 832,
                    "height": 1216,
                    "params": {
                        "n_samples": 2,
                        "scale": 6.0,
                    },
                },
            }

            missing = api.resolve_compose_render_plan(request)
            with_result = {
                **request,
                "compose": {
                    **request["compose"],
                    "agent": {
                        "model": "agent-model-v1",
                        "instructions": ["局部特写只保留脚部相关角色细节"],
                        "result": {
                            "positive": "akemi homura, bare soles, foot focus, soles toward viewer",
                            "negative": "extra toes, face focus",
                            "character_scope": "foot_detail",
                            "included_character_sections": ["character", "feet"],
                            "suppressed_character_sections": ["eyes", "upper_clothes"],
                        },
                    },
                },
            }
            ready = api.resolve_compose_render_plan(with_result)
            cached = api.resolve_compose_render_plan(request)

            self.assertEqual(
                missing["schema"],
                "tags-machine-core.compose-render-plan-resolution/v1",
            )
            self.assertEqual(missing["status"], "requires_agent")
            self.assertEqual(missing["agent_task"]["nodes"]["character"]["id"], "homura")
            self.assertEqual(missing["agent_task"]["nodes"]["action"]["id"], "foot_closeup")
            self.assertEqual(missing["agent_task"]["agent_model"], "agent-model-v1")
            self.assertNotIn("render_request", missing)

            self.assertEqual(ready["status"], "ready")
            self.assertFalse(ready["prompt_bundle"]["cache"]["cache_hit"])
            self.assertEqual(ready["prompt_bundle"]["meta"]["agent"]["agent_model"], "agent-model-v1")
            self.assertEqual(ready["render_request"]["backend"], "novelai")
            self.assertEqual(ready["render_request"]["seed"], 2468)
            self.assertEqual(ready["render_request"]["params"]["n_samples"], 2)
            self.assertEqual(ready["render_request"]["meta"]["composer_type"], "agent")
            self.assertEqual(cached["status"], "ready")
            self.assertTrue(cached["prompt_bundle"]["cache"]["cache_hit"])
            self.assertEqual(ready["render_request"], cached["render_request"])

    def test_resolve_batch_item_returns_requires_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            response = GenerationJsonApi().resolve_batch_item(
                {
                    "id": "foot_detail_001",
                    "compose": {
                        "composer": "agent",
                        "nodes": {
                            "character": str(character),
                            "action": str(action),
                        },
                        "artist": str(style),
                        "character_scope": "foot_detail",
                        "agent": {"model": "agent-model-v1"},
                        "cache": {"cache_dir": str(root / "cache" / "missing")},
                    },
                    "render": {
                        "backend": "novelai",
                        "artist": str(style),
                        "seed": 123,
                    },
                    "output": {"dir": str(root / "outputs" / "foot_detail_001")},
                }
            )

            self.assertEqual(response["schema"], "tags-machine-core.batch-item-result/v1")
            self.assertEqual(response["id"], "foot_detail_001")
            self.assertEqual(response["status"], "requires_agent")
            self.assertEqual(
                response["agent_task"]["schema"],
                "tags-machine-core.agent-composition-task/v2",
            )
            self.assertNotIn("prompt_bundle", response)
            self.assertNotIn("render_request", response)

    def test_resolve_batch_item_returns_ready_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, style = _write_sample_nodes(root)
            response = GenerationJsonApi().resolve_batch_item(
                {
                    "id": "prompt_001",
                    "compose": {
                        "composer": "full",
                        "prompt": "akemi homura, foot focus",
                        "negative": "bad anatomy",
                    },
                    "render": {
                        "backend": "novelai",
                        "artist": str(style),
                        "seed": 123,
                        "width": 832,
                        "height": 1216,
                    },
                    "output": {"dir": str(root / "outputs" / "prompt_001")},
                }
            )

            self.assertEqual(response["schema"], "tags-machine-core.batch-item-result/v1")
            self.assertEqual(response["id"], "prompt_001")
            self.assertEqual(response["status"], "ready")
            self.assertEqual(response["prompt_bundle"]["prompt"]["positive"], "akemi homura, foot focus")
            self.assertEqual(response["render_request"]["backend"], "novelai")
            self.assertEqual(response["render_request"]["seed"], 123)
            self.assertEqual(response["output"]["dir"], str(root / "outputs" / "prompt_001"))
            self.assertNotIn("agent_task", response)

    def test_cli_api_agent_entries_read_json_request_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            cache_dir = root / "cache" / "prompt"
            request_path = root / "agent_request.json"
            task_output = root / "agent_task.json"
            bundle_output = root / "agent_bundle.json"
            resolve_output = root / "agent_resolution.json"
            request_path.write_text(
                json.dumps(
                    {
                        "nodes": {
                            "character": str(character),
                            "action": str(action),
                        },
                        "artist": str(style),
                        "character_scope": "foot_detail",
                        "agent": {
                            "instructions": ["避免把眼睛和上衣放进脚部特写"],
                            "result": {
                                "positive": "akemi homura, bare soles, foot focus",
                                "negative": "extra toes, face focus",
                                "character_scope": "foot_detail",
                                "included_character_sections": ["character", "feet"],
                                "suppressed_character_sections": ["eyes", "upper_clothes"],
                            },
                        },
                        "cache": {
                            "cache_dir": str(cache_dir),
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            task_stdout = io.StringIO()
            with redirect_stdout(task_stdout):
                task_exit = main(
                    [
                        "api-agent-task",
                        str(request_path),
                        "--output",
                        str(task_output),
                    ]
                )
            bundle_stdout = io.StringIO()
            with redirect_stdout(bundle_stdout):
                bundle_exit = main(
                    [
                        "api-compose-agent",
                        str(request_path),
                        "--output",
                        str(bundle_output),
                    ]
                )
            resolve_stdout = io.StringIO()
            with redirect_stdout(resolve_stdout):
                resolve_exit = main(
                    [
                        "api-resolve-agent",
                        str(request_path),
                        "--output",
                        str(resolve_output),
                    ]
                )

            task_printed = json.loads(task_stdout.getvalue())
            task_written = json.loads(task_output.read_text(encoding="utf-8"))
            bundle_printed = json.loads(bundle_stdout.getvalue())
            bundle_written = json.loads(bundle_output.read_text(encoding="utf-8"))
            resolve_printed = json.loads(resolve_stdout.getvalue())
            resolve_written = json.loads(resolve_output.read_text(encoding="utf-8"))

            self.assertEqual(task_exit, 0)
            self.assertEqual(bundle_exit, 0)
            self.assertEqual(resolve_exit, 0)
            self.assertEqual(task_printed["cache_key"], task_written["cache_key"])
            self.assertEqual(bundle_printed["prompt"]["positive"], "akemi homura, bare soles, foot focus")
            self.assertEqual(bundle_written["meta"]["composer_type"], "agent")
            self.assertEqual(bundle_written["meta"]["composition"]["character_scope"], "foot_detail")
            self.assertEqual(resolve_printed["status"], "ready")
            self.assertEqual(resolve_written["prompt_bundle"]["meta"]["composer_type"], "agent")
            self.assertTrue(any(cache_dir.glob("*.json")))

    def test_cli_api_resolve_agent_returns_task_without_agent_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            cache_dir = root / "cache" / "prompt"
            request_path = root / "agent_request.json"
            output = root / "agent_resolution.json"
            request_path.write_text(
                json.dumps(
                    {
                        "nodes": {
                            "character": str(character),
                            "action": str(action),
                        },
                        "artist": str(style),
                        "character_scope": "foot_detail",
                        "agent": {
                            "instructions": ["避免把眼睛和上衣放进脚部特写"],
                        },
                        "cache": {
                            "cache_dir": str(cache_dir),
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "api-resolve-agent",
                        str(request_path),
                        "--output",
                        str(output),
                    ]
                )

            printed = json.loads(stdout.getvalue())
            written = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "requires_agent")
            self.assertEqual(written["schema"], "tags-machine-core.agent-compose-resolution/v1")
            self.assertEqual(written["agent_task"]["nodes"]["character"]["id"], "homura")
            self.assertEqual(written["agent_task"]["nodes"]["action"]["id"], "foot_closeup")
            self.assertFalse(any(cache_dir.glob("*.json")))

    def test_cli_api_resolve_compose_render_plan_returns_ready_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            cache_dir = root / "cache" / "prompt"
            request_path = root / "agent_plan_request.json"
            output = root / "agent_plan_resolution.json"
            request_path.write_text(
                json.dumps(
                    {
                        "compose": {
                            "nodes": {
                                "character": str(character),
                                "action": str(action),
                            },
                            "artist": str(style),
                            "character_scope": "foot_detail",
                            "agent": {
                                "instructions": ["避免把眼睛和上衣放进脚部特写"],
                                "result": {
                                    "positive": "akemi homura, bare soles, foot focus",
                                    "negative": "extra toes, face focus",
                                    "character_scope": "foot_detail",
                                    "included_character_sections": ["character", "feet"],
                                    "suppressed_character_sections": ["eyes", "upper_clothes"],
                                },
                            },
                            "cache": {
                                "cache_dir": str(cache_dir),
                            },
                        },
                        "render": {
                            "backend": "novelai",
                            "artist": str(style),
                            "seed": 123,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "api-resolve-compose-render-plan",
                        str(request_path),
                        "--output",
                        str(output),
                    ]
                )

            printed = json.loads(stdout.getvalue())
            written = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "ready")
            self.assertEqual(written["schema"], "tags-machine-core.compose-render-plan-resolution/v1")
            self.assertEqual(written["prompt_bundle"]["meta"]["composer_type"], "agent")
            self.assertEqual(written["render_request"]["backend"], "novelai")
            self.assertEqual(written["render_request"]["seed"], 123)

    def test_cli_api_resolve_compose_render_plan_returns_task_without_agent_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            cache_dir = root / "cache" / "prompt"
            request_path = root / "agent_plan_request.json"
            output = root / "agent_plan_resolution.json"
            request_path.write_text(
                json.dumps(
                    {
                        "compose": {
                            "nodes": {
                                "character": str(character),
                                "action": str(action),
                            },
                            "artist": str(style),
                            "character_scope": "foot_detail",
                            "agent": {
                                "instructions": ["避免把眼睛和上衣放进脚部特写"],
                            },
                            "cache": {
                                "cache_dir": str(cache_dir),
                            },
                        },
                        "render": {
                            "backend": "novelai",
                            "artist": str(style),
                            "seed": 123,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "api-resolve-compose-render-plan",
                        str(request_path),
                        "--output",
                        str(output),
                    ]
                )

            printed = json.loads(stdout.getvalue())
            written = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "requires_agent")
            self.assertEqual(written["schema"], "tags-machine-core.compose-render-plan-resolution/v1")
            self.assertEqual(written["agent_task"]["nodes"]["character"]["id"], "homura")
            self.assertEqual(written["agent_task"]["nodes"]["action"]["id"], "foot_closeup")
            self.assertNotIn("render_request", written)
            self.assertFalse(any(cache_dir.glob("*.json")))

    def test_cli_api_resolve_batch_item_returns_task_without_agent_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action, style = _write_sample_nodes(root)
            request_path = root / "batch_item.json"
            output = root / "batch_result.json"
            request_path.write_text(
                json.dumps(
                    {
                        "id": "foot_detail_001",
                        "compose": {
                            "composer": "agent",
                            "nodes": {
                                "character": str(character),
                                "action": str(action),
                            },
                            "artist": str(style),
                            "character_scope": "foot_detail",
                            "agent": {"model": "agent-model-v1"},
                            "cache": {"cache_dir": str(root / "cache" / "prompt")},
                        },
                        "render": {
                            "backend": "novelai",
                            "artist": str(style),
                            "seed": 123,
                        },
                        "output": {"dir": str(root / "outputs" / "foot_detail_001")},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "api-resolve-batch-item",
                        str(request_path),
                        "--output",
                        str(output),
                    ]
                )

            printed = json.loads(stdout.getvalue())
            written = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(printed["status"], "requires_agent")
            self.assertEqual(written["schema"], "tags-machine-core.batch-item-result/v1")
            self.assertEqual(written["id"], "foot_detail_001")
            self.assertEqual(written["agent_task"]["nodes"]["action"]["id"], "foot_closeup")
            self.assertNotIn("render_request", written)

    def test_example_request_files_are_valid_json_api_inputs(self):
        api = GenerationJsonApi()

        with _project_cwd():
            missing = api.resolve_agent(
                _load_example_request("agent_resolution_requires_agent.json")
            )
            bundle = api.compose_agent(
                _load_example_request("agent_compose_with_result.json")
            )
            plan = api.compose_render_plan(
                _load_example_request("compose_render_plan_novelai.json")
            )
            full_prompt_plan = api.compose_render_plan(
                _load_example_request("full_prompt_render_plan_novelai.json")
            )
            agent_plan = api.compose_render_plan(
                _load_example_request("agent_compose_render_plan_novelai.json")
            )
            missing_plan = api.resolve_compose_render_plan(
                _load_example_request("agent_compose_render_plan_requires_agent.json")
            )
            ready_plan = api.resolve_compose_render_plan(
                _load_example_request("agent_compose_render_plan_novelai.json")
            )

        self.assertEqual(missing["status"], "requires_agent")
        self.assertEqual(missing["agent_task"]["nodes"]["character"]["id"], "homura")
        self.assertEqual(missing["agent_task"]["nodes"]["action"]["id"], "foot_closeup")
        self.assertEqual(missing["agent_task"]["nodes"]["artist"]["id"], "anime_comfy")

        self.assertEqual(bundle["meta"]["composer_type"], "agent")
        artist_nodes = [node for node in bundle["meta"]["nodes"] if node["role"] == "artist"]
        self.assertEqual(artist_nodes[0]["id"], "anime_comfy")
        self.assertIn("bare soles", bundle["prompt"]["positive"])
        self.assertEqual(
            bundle["meta"]["composition"]["included_character_sections"],
            ["character", "copyright", "feet"],
        )
        self.assertEqual(
            bundle["meta"]["composition"]["suppressed_character_sections"],
            ["hair", "eyes", "upper_clothes"],
        )

        self.assertEqual(plan["prompt_bundle"]["meta"]["composer_type"], "script")
        self.assertEqual(plan["prompt_bundle"]["meta"]["composition"]["character_scope"], "foot_detail")
        self.assertIn("bare_soles", plan["prompt_bundle"]["prompt"]["positive"])
        self.assertNotIn("purple eyes", plan["prompt_bundle"]["prompt"]["positive"])
        self.assertEqual(plan["render_request"]["backend"], "novelai")
        self.assertEqual(plan["render_request"]["seed"], 123)
        self.assertEqual(plan["render_request"]["size"], {"width": 832, "height": 1216})
        self.assertEqual(plan["render_request"]["params"]["n_samples"], 1)
        self.assertEqual(plan["render_request"]["params"]["cfg_rescale"], 0.15)
        self.assertIn("v4_prompt", plan["render_request"]["params"])

        self.assertEqual(full_prompt_plan["prompt_bundle"]["meta"]["composer_type"], "script")
        self.assertEqual(full_prompt_plan["prompt_bundle"]["meta"]["nodes"], [])
        self.assertEqual(
            full_prompt_plan["prompt_bundle"]["meta"]["composition"]["included_character_sections"],
            [],
        )
        self.assertIn("bare soles", full_prompt_plan["prompt_bundle"]["prompt"]["positive"])
        self.assertIn("anime style", full_prompt_plan["render_request"]["prompt"])
        self.assertIn("worst quality", full_prompt_plan["render_request"]["negative_prompt"])
        self.assertIn("v4_prompt", full_prompt_plan["render_request"]["params"])

        self.assertEqual(agent_plan["prompt_bundle"]["meta"]["composer_type"], "agent")
        self.assertEqual(agent_plan["render_request"]["meta"]["composer_type"], "agent")
        self.assertEqual(agent_plan["render_request"]["backend"], "novelai")
        self.assertIn("low angle close-up", agent_plan["render_request"]["prompt"])
        self.assertIn("worst quality", agent_plan["render_request"]["negative_prompt"])
        self.assertEqual(missing_plan["status"], "requires_agent")
        self.assertEqual(missing_plan["agent_task"]["nodes"]["action"]["id"], "foot_closeup")
        self.assertEqual(ready_plan["status"], "ready")
        self.assertEqual(ready_plan["render_request"]["backend"], "novelai")
        self.assertEqual(ready_plan["prompt_bundle"]["meta"]["composer_type"], "agent")

    def test_json_api_contract_documents_example_request_files(self):
        doc_path = PROJECT_ROOT / "docs" / "json_api_contract_v1.md"
        doc = doc_path.read_text(encoding="utf-8")
        documented = sorted(
            set(re.findall(r"examples/requests/[A-Za-z0-9_.-]+\.json", doc))
        )
        example_files = sorted(
            f"examples/requests/{path.name}"
            for path in (PROJECT_ROOT / "examples" / "requests").glob("*.json")
        )

        self.assertEqual(documented, example_files)
        for relative_path in documented:
            self.assertTrue((PROJECT_ROOT / relative_path).is_file())

    def test_json_api_response_shape_examples_match_runtime_outputs(self):
        api = GenerationJsonApi()
        generate_api = GenerationJsonApi(generation_executor=_shape_generation_executor)
        shape_path = PROJECT_ROOT / "examples" / "responses" / "json_api_response_shapes.json"
        shapes = json.loads(shape_path.read_text(encoding="utf-8"))

        self.assertEqual(
            shapes["schema"],
            "tags-machine-core.json-api-response-shapes/v1",
        )
        shape_requests = sorted(case["request"] for case in shapes["cases"])
        example_requests = sorted(
            f"examples/requests/{path.name}"
            for path in (PROJECT_ROOT / "examples" / "requests").glob("*.json")
        )
        self.assertEqual(shape_requests, example_requests)
        self.assertEqual(
            len({case["id"] for case in shapes["cases"]}),
            len(shapes["cases"]),
        )

        with _project_cwd():
            for case in shapes["cases"]:
                with self.subTest(case=case["id"]):
                    request = json.loads(
                        (PROJECT_ROOT / case["request"]).read_text(encoding="utf-8")
                    )
                    case_api = generate_api if case["entry"] == "generate" else api
                    result = getattr(case_api, case["entry"])(request)
                    expected = case["expect"]
                    for path, value in expected.get("equals", {}).items():
                        self.assertEqual(_json_path(result, path), value)
                    for path, text in expected.get("contains", {}).items():
                        self.assertIn(text, _json_path(result, path))
                    for path in expected.get("required", []):
                        self.assertTrue(_json_path_exists(result, path), path)
                    for path in expected.get("absent", []):
                        self.assertFalse(_json_path_exists(result, path), path)

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

    def test_example_generate_request_uses_injected_executor(self):
        calls = []

        def executor(render_request: RenderRequest, request_data):
            calls.append((render_request, request_data))
            return _shape_generation_executor(render_request, request_data)

        with _project_cwd():
            result = GenerationJsonApi(generation_executor=executor).generate(
                _load_example_request("generate_novelai_mock.json")
            )

        self.assertEqual(result["schema"], "tags-machine-core.generation-result/v1")
        self.assertEqual(result["backend"], "novelai")
        self.assertEqual(result["request_body"]["input"], "akemi homura, bare soles, foot focus")
        self.assertEqual(result["request_body"]["parameters"]["steps"], 28)
        self.assertEqual(result["request_body"]["parameters"]["width"], 832)
        self.assertEqual(result["request_body"]["parameters"]["height"], 1216)
        self.assertEqual(result["request_body"]["parameters"]["reference_image_multiple"], [])
        self.assertEqual(result["request_body"]["parameters"]["reference_strength_multiple"], [])
        self.assertEqual(
            result["request_body"]["parameters"]["reference_information_extracted_multiple"],
            [],
        )
        self.assertEqual(result["request_body"]["parameters"]["director_reference_images"], [])
        self.assertEqual(result["png_info"]["images"], [])
        self.assertEqual(calls[0][1]["queue"]["job_id"], "example-generate-001")

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
                    png_info={
                        "images": [
                            {
                                "path": str(generated_image),
                                "error": "mock executor did not write PNG metadata",
                            }
                        ]
                    },
                )

            api = GenerationJsonApi(generation_executor=executor)
            planned = api.compose_render_plan(
                {
                    "compose": {
                        "nodes": {
                            "character": str(character),
                            "action": str(action),
                        },
                        "artist": str(style),
                    },
                    "render": {
                        "backend": "novelai",
                        "artist": str(style),
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
                patch("tags_machine_core.execution.NovelAIClient") as client_cls,
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
                retry_interval=None,
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

    def test_cli_api_generate_uses_unified_execution_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _write_config(root)
            output_dir = root / "api_outputs"
            request = root / "api_generate.json"
            request.write_text(
                json.dumps(
                    {
                        "render_request": {
                            "backend": "novelai",
                            "prompt": "akemi homura",
                            "seed": 123,
                        },
                        "output_dir": str(output_dir),
                    }
                ),
                encoding="utf-8",
            )

            with patch("tags_machine_core.cli._execute_render_request") as executor:
                executor.return_value = GenerationResult(
                    backend="novelai",
                    request_body={"parameters": {"seed": 123}},
                )

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "api-generate",
                            str(request),
                            "--config",
                            str(config),
                        ]
                    )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(data["backend"], "novelai")
            executor.assert_called_once()
            called_config, called_request = executor.call_args.args
            self.assertEqual(called_config.novelai.base_url, "http://novelai.local")
            self.assertEqual(called_request.backend, "novelai")
            self.assertEqual(called_request.prompt, "akemi homura")
            self.assertEqual(executor.call_args.kwargs["output_dir"], str(output_dir))
            self.assertEqual(executor.call_args.kwargs["image_format"], "png")
            self.assertIs(executor.call_args.kwargs["allow_experimental_backend"], False)

    def test_cli_api_generate_supports_comfyui_backend_by_default(self):
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
                            "params": {"workflow_json": {}},
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch("tags_machine_core.cli._execute_render_request") as executor:
                executor.return_value = GenerationResult(
                    backend="comfyui",
                    request_body={"prompt": {}},
                )
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

            self.assertEqual(exit_code, 0)
            executor.assert_called_once()
            self.assertEqual(executor.call_args.args[1].backend, "comfyui")
            self.assertTrue(response.exists())

    def test_cli_api_generate_rejects_sd_backend_in_v1_scope_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _write_config(root)
            request = root / "api_generate_sd.json"
            response = root / "api_generate_response.json"
            request.write_text(
                json.dumps(
                    {
                        "render_request": {
                            "backend": "sd",
                            "prompt": "akemi homura",
                            "negative_prompt": "bad anatomy",
                            "params": {"steps": 24},
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch("tags_machine_core.cli._execute_render_request") as executor:
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

            self.assertIn("api-generate", str(raised.exception))
            self.assertIn("only NovelAI", str(raised.exception))
            self.assertIn("Use execute-render-request", str(raised.exception))
            executor.assert_not_called()
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


def _without_trace_locations(value):
    if isinstance(value, dict):
        is_node_ref = "role" in value and "id" in value
        return {
            key: _without_trace_locations(item)
            for key, item in value.items()
            if key != "source_nodes" and not (is_node_ref and key == "ref")
        }
    if isinstance(value, list):
        return [_without_trace_locations(item) for item in value]
    return value


def _shape_generation_executor(render_request: RenderRequest, request_data):
    return GenerationResult(
        backend=render_request.backend,
        request_body={
            "input": render_request.prompt,
            "model": render_request.model,
            "action": render_request.meta.get("action", "generate"),
            "parameters": {
                **render_request.params,
                "seed": render_request.seed,
                "width": render_request.size.width,
                "height": render_request.size.height,
            },
        },
        png_info={"images": []},
        cache_hit=False,
    )


def _json_path(value, path: str):
    exists, result = _try_json_path(value, path)
    if not exists:
        raise AssertionError(f"JSON path does not exist: {path}")
    return result


def _json_path_exists(value, path: str) -> bool:
    exists, _ = _try_json_path(value, path)
    return exists


def _try_json_path(value, path: str):
    if not path.startswith("$."):
        raise ValueError(f"Unsupported JSON path: {path}")
    current = value
    for segment in path[2:].split("."):
        name, indexes = _split_json_path_segment(segment)
        if not isinstance(current, dict) or name not in current:
            return False, None
        current = current[name]
        for index in indexes:
            if not isinstance(current, list) or index >= len(current):
                return False, None
            current = current[index]
    return True, current


def _split_json_path_segment(segment: str) -> tuple[str, list[int]]:
    match = re.fullmatch(r"([A-Za-z0-9_]+)((?:\[\d+\])*)", segment)
    if not match:
        raise ValueError(f"Unsupported JSON path segment: {segment}")
    indexes = [int(item) for item in re.findall(r"\[(\d+)\]", match.group(2))]
    return match.group(1), indexes


if __name__ == "__main__":
    unittest.main()
