import io
import json
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from tags_machine_core.cli import build_parser as build_core_parser, main
from tags_machine_core.nodes import NodeReader
from tags_machine_core.services import GenerationService
from tags_machine_core.verification import verify_acceptance_suite
from tools.legacy_migration.cli import main as legacy_migration_main


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _png_bytes_with_text(chunks: dict[str, str]) -> bytes:
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)))
    for key, value in chunks.items():
        png.extend(_png_chunk(b"tEXt", key.encode("latin-1") + b"\x00" + value.encode("utf-8")))
    png.extend(_png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")))
    png.extend(_png_chunk(b"IEND", b""))
    return bytes(png)


class CliNodesTest(unittest.TestCase):
    def test_core_cli_does_not_expose_legacy_migration_commands(self):
        help_text = build_core_parser().format_help()
        for command in (
            "migrate-artist-tags",
            "migrate-action-tags",
            "migrate-character-tags",
            "migrate-background-tags",
            "audit-legacy-tags",
            "plan-legacy-tags-migration",
            "apply-legacy-tags-migration",
        ):
            self.assertNotIn(command, help_text)

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
schema: tags-machine.artist/v1
kind: artist
id: cross_backend_style
tags:
  artist:
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
      reference_information_extracted_multiple:
        - 0.6
      director_reference_images:
        - director-abc
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
    inputs:
      positive_prompt: "17.inputs.text"
      negative_prompt: "17.inputs.negative"
      width: "12.inputs.width"
      height: "12.inputs.height"
      seed: "12.inputs.seed"
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

    def _write_config(self, root: Path) -> Path:
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
comfyui:
  base_url: "http://comfy.local"
  timeout: 30
sd:
  base_url: "http://sd.local"
  timeout: 45
""".strip(),
            encoding="utf-8",
        )
        return config

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
            self.assertIn("2.0::akemi_homura::", data["prompt"]["positive"])
            self.assertIn("bare_soles", data["prompt"]["positive"])
            self.assertIn("foot_focus", data["prompt"]["positive"])
            self.assertNotIn("purple eyes", data["prompt"]["positive"])
            self.assertNotIn("school uniform", data["prompt"]["positive"])
            self.assertIn("extra_toes", data["prompt"]["negative"])

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
            background_refs = [
                node for node in data["meta"]["nodes"] if node["role"] == "background"
            ]
            self.assertEqual(background_refs[0]["id"], "simple_room")
            self.assertIn("simple_room", data["prompt"]["positive"])
            self.assertIn("soft_window_light", data["prompt"]["positive"])
            self.assertIn("crowded_background", data["prompt"]["negative"])

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
                        "--agent-model",
                        "agent-model-v1",
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
                        "--agent-model",
                        "agent-model-v1",
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
                        "--agent-model",
                        "agent-model-v1",
                        "--cache-dir",
                        str(cache_dir),
                    ]
                )
            second_data = json.loads(second_stdout.getvalue())

            self.assertEqual(task_exit_code, 0)
            self.assertEqual(first_exit_code, 0)
            self.assertEqual(second_exit_code, 0)
            self.assertEqual(task_data["schema"], "tags-machine-core.agent-composition-task/v2")
            self.assertEqual(task_data["agent_model"], "agent-model-v1")
            self.assertEqual(first_data["cache"]["cache_key"], task_data["cache_key"])
            self.assertFalse(first_data["cache"]["cache_hit"])
            self.assertTrue(second_data["cache"]["cache_hit"])
            self.assertEqual(second_data["prompt"]["positive"], "akemi homura, bare soles, foot focus")
            self.assertEqual(second_data["meta"]["composer_type"], "agent")
            self.assertEqual(first_data["meta"]["agent"]["agent_model"], "agent-model-v1")

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
                        "--artist-node",
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
            artist_refs = [node for node in data["meta"]["node_refs"] if node["role"] == "artist"]
            self.assertEqual(artist_refs[0]["id"], "cross_backend_style")

    def test_render_plan_nodes_expands_comfyui_workflow_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_sample_nodes(root)
            style = root / "style_with_workflow"
            workflow_dir = style / "workflows"
            workflow_dir.mkdir(parents=True)
            (workflow_dir / "portrait.json").write_text(
                json.dumps(
                    {
                        "12": {"class_type": "KSampler", "inputs": {"cfg": 5.0}},
                        "17": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                    }
                ),
                encoding="utf-8",
            )
            (style / "node.yaml").write_text(
                """
schema: tags-machine.artist/v1
kind: artist
id: comfy_workflow_style
tags:
  artist:
    - comfy workflow style
renderers:
  comfyui:
    workflow: portrait_workflow
    workflow_path: workflows/portrait.json
    checkpoint: anime_comfy.safetensors
    inputs:
      positive_prompt: "17.inputs.text"
      negative_prompt: "17.inputs.negative"
      width: "12.inputs.width"
      height: "12.inputs.height"
      seed: "12.inputs.seed"
    node_overrides:
      "17.inputs.text": "{positive_prompt}"
      "18.inputs.seed": "{seed}"
      "18.inputs.width": "{width}"
    params:
      steps: 32
      cfg: 6.5
""".strip(),
                encoding="utf-8",
            )

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
                        "--artist-node",
                        str(style),
                        "--seed",
                        "123",
                    ]
                )

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["backend"], "comfyui")
            self.assertEqual(data["params"]["workflow"], "portrait_workflow")
            self.assertEqual(data["params"]["workflow_json"]["12"]["inputs"]["cfg"], 5.0)
            self.assertEqual(data["params"]["workflow_json"]["17"]["inputs"]["text"], "")
            self.assertEqual(
                data["params"]["node_overrides"]["17.inputs.text"],
                "1girl, 2.0::akemi_homura::, bare_soles, foot_focus",
            )
            self.assertEqual(data["params"]["node_overrides"]["18.inputs.seed"], 123)
            self.assertEqual(data["params"]["node_overrides"]["18.inputs.width"], 1024)

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
                        "--artist-node",
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
            self.assertEqual(data["params"]["reference_information_extracted_multiple"], [0.6])
            self.assertEqual(data["params"]["director_reference_images"], ["director-abc"])
            self.assertIn("style prefix", data["prompt"])
            self.assertIn("2.0::akemi_homura::", data["prompt"])
            self.assertIn("anime style", data["prompt"])
            self.assertIn("{best quality}", data["prompt"])
            self.assertIn("style suffix", data["prompt"])
            self.assertIn("extra_toes", data["negative_prompt"])
            self.assertIn("lowres", data["negative_prompt"])
            self.assertIn("bad anatomy", data["negative_prompt"])
            artist_refs = [node for node in data["meta"]["node_refs"] if node["role"] == "artist"]
            self.assertEqual(artist_refs[0]["id"], "cross_backend_style")

    def test_archive_novelai_acceptance_nodes_builds_core_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_sample_nodes(root)
            style = self._write_style_node(root)
            reader = NodeReader()
            service = GenerationService()
            bundle = service.compose_nodes(
                character=reader.read(character),
                action=reader.read(action),
                artist=reader.read(style),
            )
            request = service.build_novelai_request(
                bundle,
                seed=789,
                width=832,
                height=1216,
                artist=reader.read(style),
            )
            legacy = root / "legacy_request.json"
            legacy_image = root / "legacy.png"
            core_image = root / "generated.png"
            legacy.write_text(
                json.dumps(
                    {
                        "input": request.prompt,
                        "model": request.model,
                        "action": "generate",
                        "parameters": request.params,
                    }
                ),
                encoding="utf-8",
            )
            legacy_image.write_bytes(
                _png_bytes_with_text({"Comment": json.dumps(request.params)})
            )
            core_image.write_bytes(
                _png_bytes_with_text({"Comment": json.dumps(request.params)})
            )
            generation_result = root / "generation_result.json"
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [
                            {
                                "path": str(core_image),
                                "filename": "generated.png",
                                "meta": {"index": 0},
                            }
                        ],
                        "request_body": {
                            "input": request.prompt,
                            "model": request.model,
                            "action": "generate",
                            "parameters": request.params,
                        },
                        "png_info": {
                            "images": [
                                {
                                    "path": str(core_image),
                                    "parameters": request.params,
                                }
                            ]
                        },
                        "cache_hit": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "archive-novelai-acceptance-nodes",
                        "--case-id",
                        "foot_detail_homura_001",
                        "--output-dir",
                        str(root / "acceptance"),
                        "--legacy-source",
                        str(legacy),
                        "--legacy-image",
                        str(legacy_image),
                        "--character",
                        str(character),
                        "--action",
                        str(action),
                        "--artist-node",
                        str(style),
                        "--seed",
                        "789",
                        "--width",
                        "832",
                        "--height",
                        "1216",
                        "--generation-result",
                        str(generation_result),
                        "--required-case",
                        "foot_detail",
                    ]
                )
            archive = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(archive["result"], "pass")
            case_dir = Path(archive["case_dir"])
            render_request_path = case_dir / "core" / "render_request.json"
            prompt_bundle_path = case_dir / "core" / "prompt_bundle.json"
            self.assertTrue(render_request_path.exists())
            self.assertTrue(prompt_bundle_path.exists())
            self.assertTrue((case_dir / "legacy" / "source.json").exists())
            self.assertTrue((case_dir / "legacy" / "image.png").exists())
            self.assertTrue((case_dir / "core" / "image.png").exists())
            generated_request = json.loads(render_request_path.read_text(encoding="utf-8"))
            generated_bundle = json.loads(prompt_bundle_path.read_text(encoding="utf-8"))
            generated_result = json.loads(
                (case_dir / "core" / "generation_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(generated_request["backend"], "novelai")
            self.assertEqual(generated_request["params"]["reference_image_multiple"], ["abc"])
            self.assertEqual(generated_request["params"]["reference_strength_multiple"], [0.25])
            self.assertEqual(
                generated_request["params"]["reference_information_extracted_multiple"],
                [0.6],
            )
            self.assertEqual(
                generated_request["params"]["director_reference_images"],
                ["director-abc"],
            )
            self.assertEqual(generated_bundle["meta"]["composition"]["character_scope"], "foot_detail")
            self.assertEqual(
                archive["record"]["core"]["render_request_path"],
                "core/render_request.json",
            )
            self.assertEqual(
                archive["record"]["core"]["generation_result_path"],
                "core/generation_result.json",
            )
            self.assertEqual(archive["record"]["core"]["image_path"], "core/image.png")
            self.assertEqual(generated_result["images"][0]["path"], "image.png")
            self.assertEqual(generated_result["png_info"]["images"][0]["path"], "image.png")
            self.assertEqual(
                archive["record"]["generation_result_evidence"]["request_body"]["diff"][
                    "diff_count"
                ],
                0,
            )
            raw_generation_params = generated_result["request_body"]["parameters"]
            self.assertEqual(raw_generation_params["reference_image_multiple"], ["abc"])
            self.assertEqual(raw_generation_params["reference_strength_multiple"], [0.25])
            self.assertEqual(raw_generation_params["reference_information_extracted_multiple"], [0.6])
            self.assertEqual(raw_generation_params["director_reference_images"], ["director-abc"])
            generation_params = archive["record"]["generation_result_evidence"]["request_body"][
                "normalized"
            ]["parameters"]
            self.assertEqual(generation_params["reference_image_multiple"][0]["type"], "string")
            self.assertEqual(generation_params["reference_image_multiple"][0]["chars"], 3)
            self.assertEqual(generation_params["reference_strength_multiple"], [0.25])
            self.assertEqual(generation_params["reference_information_extracted_multiple"], [0.6])
            self.assertEqual(generation_params["director_reference_images"][0]["type"], "string")
            self.assertEqual(generation_params["director_reference_images"][0]["chars"], 12)
            suite = verify_acceptance_suite(root / "acceptance" / "suite.yaml")
            self.assertTrue(suite["match"])
            self.assertEqual(suite["missing_required_cases"], [])
            legacy_image.unlink()
            core_image.unlink()
            strict_suite = verify_acceptance_suite(
                root / "acceptance" / "suite.yaml",
                require_legacy_evidence=True,
            )
            self.assertTrue(strict_suite["match"])
            self.assertEqual(strict_suite["legacy_oracle_evidence_fail_count"], 0)

    def test_archive_novelai_acceptance_nodes_matches_cli_prompt_and_render_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character, action = self._write_sample_nodes(root)
            style = self._write_style_node(root)

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
            prompt_bundle = json.loads(compose_stdout.getvalue())

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
                        '{"scale": 6.0, "cfg_rescale": 0.15}',
                    ]
                )
            render_request = json.loads(render_stdout.getvalue())

            legacy = root / "legacy_request.json"
            legacy.write_text(
                json.dumps(
                    {
                        "input": render_request["prompt"],
                        "model": render_request["model"],
                        "action": "generate",
                        "parameters": render_request["params"],
                    }
                ),
                encoding="utf-8",
            )

            archive_stdout = io.StringIO()
            with redirect_stdout(archive_stdout):
                archive_exit = main(
                    [
                        "archive-novelai-acceptance-nodes",
                        "--case-id",
                        "foot_detail_homura_parity_001",
                        "--output-dir",
                        str(root / "acceptance"),
                        "--legacy-source",
                        str(legacy),
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
                        '{"scale": 6.0, "cfg_rescale": 0.15}',
                        "--required-case",
                        "foot_detail",
                    ]
                )
            archive = json.loads(archive_stdout.getvalue())

            case_dir = Path(archive["case_dir"])
            archived_bundle = json.loads(
                (case_dir / "core" / "prompt_bundle.json").read_text(encoding="utf-8")
            )
            archived_request = json.loads(
                (case_dir / "core" / "render_request.json").read_text(encoding="utf-8")
            )

            self.assertEqual(compose_exit, 0)
            self.assertEqual(render_exit, 0)
            self.assertEqual(archive_exit, 0)
            self.assertEqual(archive["result"], "pass")
            self.assertEqual(archived_bundle["prompt"], prompt_bundle["prompt"])
            self.assertEqual(
                archived_bundle["meta"]["composition"],
                prompt_bundle["meta"]["composition"],
            )
            self.assertEqual(
                sorted((node["role"], node["id"]) for node in archived_bundle["meta"]["nodes"]),
                sorted((node["role"], node["id"]) for node in prompt_bundle["meta"]["nodes"]),
            )
            self.assertEqual(archived_request, render_request)
            self.assertTrue(archive["record"]["diff"]["normalized_equal"])
            self.assertEqual(archived_request["params"]["reference_image_multiple"], ["abc"])
            self.assertEqual(archived_request["params"]["director_reference_images"], ["director-abc"])
            self.assertEqual(archived_request["params"]["cfg_rescale"], 0.15)

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
                        "--artist-node",
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
            artist_refs = [node for node in data["meta"]["node_refs"] if node["role"] == "artist"]
            self.assertEqual(artist_refs[0]["id"], "cross_backend_style")

    def test_execute_render_request_queues_comfyui_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            request = root / "comfy_request.json"
            request.write_text(
                json.dumps(
                    {
                        "backend": "comfyui",
                        "prompt": "akemi homura",
                        "params": {
                            "workflow_json": {
                                "1": {"inputs": {"text": "akemi homura"}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch("tags_machine_core.execution.ComfyUIClient") as client_cls:
                client = client_cls.return_value
                client.queue_prompt.return_value = SimpleNamespace(
                    prompt_id="abc123",
                    raw={"prompt_id": "abc123"},
                )
                client.build_payload.return_value = {
                    "prompt": {"1": {"inputs": {"text": "akemi homura"}}},
                    "client_id": "client-1",
                }

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "execute-render-request",
                            str(request),
                            "--config",
                            str(config),
                            "--allow-experimental-backend",
                            "--client-id",
                            "client-1",
                            "--comfyui-no-wait",
                        ]
                    )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            client_cls.assert_called_once_with(
                base_url="http://comfy.local",
                timeout=30,
                retry=3,
                retry_interval=2.0,
            )
            client.queue_prompt.assert_called_once()
            self.assertEqual(client.queue_prompt.call_args.kwargs["client_id"], "client-1")
            client.generate_images.assert_not_called()
            self.assertEqual(data["backend"], "comfyui")
            self.assertEqual(data["images"], [])
            self.assertEqual(data["request_body"]["client_id"], "client-1")
            self.assertEqual(data["png_info"]["comfyui"]["prompt_id"], "abc123")

    def test_execute_render_request_supports_comfyui_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            request = root / "comfy_request.json"
            request.write_text(
                json.dumps(
                    {
                        "backend": "comfyui",
                        "prompt": "akemi homura",
                        "params": {"workflow_json": {}},
                    }
                ),
                encoding="utf-8",
            )

            with patch("tags_machine_core.execution.ComfyUIClient") as client_cls:
                client = client_cls.return_value
                client.queue_prompt.return_value = SimpleNamespace(
                    prompt_id="abc123",
                    raw={"prompt_id": "abc123"},
                )
                client.build_payload.return_value = {
                    "prompt": {},
                    "client_id": "client-default",
                }
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                    [
                        "execute-render-request",
                        str(request),
                        "--config",
                        str(config),
                        "--client-id",
                        "client-default",
                        "--comfyui-no-wait",
                    ]
                )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            client.queue_prompt.assert_called_once()
            self.assertEqual(data["backend"], "comfyui")
            self.assertEqual(data["png_info"]["comfyui"]["prompt_id"], "abc123")

    def test_execute_render_request_executes_novelai_without_experimental_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            output_dir = root / "novelai_outputs"
            request = root / "novelai_request.json"
            request.write_text(
                json.dumps(
                    {
                        "backend": "novelai",
                        "prompt": "akemi homura",
                        "negative_prompt": "bad anatomy",
                        "seed": 135,
                        "params": {
                            "prompt": "akemi homura",
                            "negative_prompt": "bad anatomy",
                            "seed": 135,
                            "n_samples": 2,
                        },
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
                    "model": "nai-diffusion-4-5-full",
                    "action": "generate",
                    "parameters": {
                        "prompt": "akemi homura",
                        "negative_prompt": "bad anatomy",
                        "seed": 135,
                        "n_samples": 2,
                    },
                }

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "execute-render-request",
                            str(request),
                            "--config",
                            str(config),
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            client_cls.assert_called_once_with(
                access_token="token",
                base_url="https://image.novelai.net",
                timeout=120,
                retry=3,
                retry_interval=None,
            )
            self.assertEqual(client.generate_images.call_count, 2)
            called_requests = [call.args[0] for call in client.generate_images.call_args_list]
            self.assertTrue(all(item.backend == "novelai" for item in called_requests))
            self.assertEqual([item.params["n_samples"] for item in called_requests], [1, 1])
            self.assertEqual([item.seed for item in called_requests], [135, 136])
            self.assertEqual(data["backend"], "novelai")
            self.assertTrue(data["request_body"]["split_batch"])
            self.assertEqual(len(data["request_body"]["requests"]), 2)
            self.assertEqual(len(data["images"]), 2)
            saved_path = Path(data["images"][0]["path"])
            self.assertEqual(saved_path.parent, output_dir)
            self.assertEqual(saved_path.suffix, ".png")
            self.assertEqual(saved_path.read_bytes(), b"image-bytes")
            self.assertIn("Not a PNG file", data["png_info"]["images"][0]["error"])

    def test_execute_render_request_saves_comfyui_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            output_dir = root / "comfy_outputs"
            request = root / "comfy_request.json"
            request.write_text(
                json.dumps(
                    {
                        "backend": "comfyui",
                        "prompt": "akemi homura",
                        "seed": 222,
                        "params": {
                            "workflow_json": {
                                "1": {"inputs": {"text": "akemi homura"}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            image_bytes = _png_bytes_with_text(
                {
                    "Comment": json.dumps(
                        {
                            "prompt": "akemi homura",
                            "seed": 222,
                        }
                    ),
                    "Source": "ComfyUI",
                }
            )
            history = {
                "abc123": {
                    "outputs": {
                        "7": {
                            "images": [
                                {
                                    "filename": "ComfyUI_00001_.png",
                                    "subfolder": "",
                                    "type": "output",
                                }
                            ]
                        }
                    }
                }
            }

            with patch("tags_machine_core.execution.ComfyUIClient") as client_cls:
                client = client_cls.return_value
                client.generate_images.return_value = SimpleNamespace(
                    prompt_id="abc123",
                    queue_raw={"prompt_id": "abc123"},
                    history=history,
                    images=[
                        SimpleNamespace(
                            filename="ComfyUI_00001_.png",
                            content=image_bytes,
                            image_type="output",
                            node_id="7",
                        )
                    ],
                )
                client.build_payload.return_value = {
                    "prompt": {"1": {"inputs": {"text": "akemi homura"}}},
                    "client_id": "client-1",
                }

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "execute-render-request",
                            str(request),
                            "--config",
                            str(config),
                            "--allow-experimental-backend",
                            "--output-dir",
                            str(output_dir),
                            "--client-id",
                            "client-1",
                            "--comfyui-poll-interval",
                            "0",
                            "--comfyui-max-wait-seconds",
                            "1",
                        ]
                    )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            client.generate_images.assert_called_once()
            self.assertEqual(client.generate_images.call_args.kwargs["client_id"], "client-1")
            self.assertEqual(client.generate_images.call_args.kwargs["poll_interval"], 0)
            self.assertEqual(client.generate_images.call_args.kwargs["max_wait_seconds"], 1)
            self.assertEqual(data["backend"], "comfyui")
            self.assertEqual(data["png_info"]["comfyui"]["prompt_id"], "abc123")
            self.assertEqual(data["png_info"]["comfyui"]["history"], history)
            self.assertEqual(len(data["images"]), 1)
            saved_path = Path(data["images"][0]["path"])
            self.assertEqual(saved_path.parent, output_dir)
            self.assertNotEqual(saved_path.read_bytes(), image_bytes)
            self.assertTrue(saved_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(data["images"][0]["meta"]["node_id"], "7")
            self.assertEqual(data["images"][0]["meta"]["image_type"], "output")
            png_info = data["png_info"]["images"][0]
            self.assertEqual(png_info["parameters"]["prompt"], "akemi homura")
            self.assertEqual(png_info["parameters"]["seed"], 222)
            self.assertEqual(png_info["png_text"]["Source"], "ComfyUI")
            self.assertIn("tags_machine_core", png_info["png_text"])

    def test_execute_render_request_saves_sd_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            output_dir = root / "custom_outputs"
            request = root / "sd_request.json"
            request.write_text(
                json.dumps(
                    {
                        "backend": "sd",
                        "prompt": "akemi homura",
                        "negative_prompt": "bad anatomy",
                        "seed": 321,
                        "size": {"width": 832, "height": 1216},
                        "params": {"steps": 24},
                    }
                ),
                encoding="utf-8",
            )

            with patch("tags_machine_core.execution.SDClient") as client_cls:
                client = client_cls.return_value
                client.generate_images.return_value = [
                    SimpleNamespace(filename="sd_result.png", content=b"png-bytes")
                ]
                client.build_payload.return_value = {
                    "prompt": "akemi homura",
                    "negative_prompt": "bad anatomy",
                    "seed": 321,
                }

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "execute-render-request",
                            str(request),
                            "--config",
                            str(config),
                            "--allow-experimental-backend",
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            client_cls.assert_called_once_with(base_url="http://sd.local", timeout=45)
            client.generate_images.assert_called_once()
            self.assertEqual(data["backend"], "sd")
            self.assertEqual(data["request_body"]["seed"], 321)
            self.assertEqual(len(data["images"]), 1)
            saved_path = Path(data["images"][0]["path"])
            self.assertEqual(saved_path.parent, output_dir)
            self.assertEqual(saved_path.read_bytes(), b"png-bytes")
            self.assertIn("Not a PNG file", data["png_info"]["images"][0]["error"])

    def test_execute_render_request_reads_saved_png_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            output_dir = root / "outputs"
            request = root / "sd_request.json"
            request.write_text(
                json.dumps(
                    {
                        "backend": "sd",
                        "prompt": "akemi homura",
                        "seed": 654,
                        "params": {"steps": 24},
                    }
                ),
                encoding="utf-8",
            )
            image_bytes = _png_bytes_with_text(
                {
                    "Comment": json.dumps(
                        {
                            "prompt": "akemi homura",
                            "negative_prompt": "bad anatomy",
                            "seed": 654,
                        }
                    ),
                    "Source": "Stable Diffusion WebUI",
                }
            )

            with patch("tags_machine_core.execution.SDClient") as client_cls:
                client = client_cls.return_value
                client.generate_images.return_value = [
                    SimpleNamespace(filename="sd_result.png", content=image_bytes)
                ]
                client.build_payload.return_value = {"prompt": "akemi homura", "seed": 654}

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "execute-render-request",
                            str(request),
                            "--config",
                            str(config),
                            "--allow-experimental-backend",
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            png_info = data["png_info"]["images"][0]
            self.assertEqual(png_info["parameters"]["prompt"], "akemi homura")
            self.assertEqual(png_info["parameters"]["seed"], 654)
            self.assertEqual(png_info["png_text"]["Source"], "Stable Diffusion WebUI")
            self.assertEqual(Path(png_info["path"]).parent, output_dir)

    def test_migrate_style_tags_command_writes_structured_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            style_dir = root / "legacy_style"
            style_dir.mkdir()
            (style_dir / "tags.txt").write_text(
                """
style prefix,
style suffix, best quality
=
origin_uc, lowres, bad anatomy
after_uc, extra fingers
gen_json, {"sampler": "k_euler_ancestral", "steps": 28, "reference_image_multiple": ["abc"], "reference_strength_multiple": [0.2]}
""".strip(),
                encoding="utf-8",
            )
            output = style_dir / "node.yaml"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = legacy_migration_main(
                    [
                        "migrate-artist-tags",
                        str(style_dir),
                        "--id",
                        "migrated_style",
                        "--output",
                        str(output),
                    ]
                )
            data = json.loads(stdout.getvalue())
            node = NodeReader().read(output)

            self.assertEqual(exit_code, 0)
            self.assertEqual(data["id"], "migrated_style")
            self.assertTrue(output.exists())
            self.assertEqual(node.kind, "artist")
            self.assertEqual(node.id, "migrated_style")
            self.assertEqual(node.tags["artist"], ["style prefix", "style suffix, best quality"])
            self.assertFalse(node.renderers["novelai"]["include_common_tags"])
            self.assertEqual(node.renderers["novelai"]["negative_prompt"], ["lowres, bad anatomy"])
            self.assertEqual(node.renderers["novelai"]["after_negative_prompt"], ["extra fingers"])
            self.assertEqual(node.renderers["novelai"]["params"]["reference_image_multiple"], ["abc"])
            self.assertEqual(node.renderers["novelai"]["params"]["reference_strength_multiple"], [0.2])

    def test_legacy_migration_output_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            style_dir = root / "legacy_style"
            style_dir.mkdir()
            (style_dir / "tags.txt").write_text("style prompt", encoding="utf-8")
            output = style_dir / "node.yaml"
            output.write_text("existing", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                legacy_migration_main(
                    [
                        "migrate-artist-tags",
                        str(style_dir),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "existing")

            with redirect_stdout(io.StringIO()):
                exit_code = legacy_migration_main(
                    [
                        "migrate-artist-tags",
                        str(style_dir),
                        "--output",
                        str(output),
                        "--overwrite",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(NodeReader().read(output).kind, "artist")

    def test_migrate_background_tags_command_writes_structured_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            background_dir = root / "legacy_background"
            background_dir.mkdir()
            (background_dir / "tags.txt").write_text(
                """
simple room,
wooden floor
=
origin_uc, crowded background
after_uc, messy room
gen_json, {"sampler": "ignored_for_background"}
""".strip(),
                encoding="utf-8",
            )
            output = background_dir / "meta.yaml"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = legacy_migration_main(
                    [
                        "migrate-background-tags",
                        str(background_dir),
                        "--id",
                        "migrated_background",
                        "--output",
                        str(output),
                    ]
                )
            data = json.loads(stdout.getvalue())
            node = NodeReader().read(output)

            self.assertEqual(exit_code, 0)
            self.assertEqual(data["id"], "migrated_background")
            self.assertTrue(output.exists())
            self.assertEqual(node.kind, "background")
            self.assertEqual(node.id, "migrated_background")
            self.assertEqual(node.tags["background"], ["simple room", "wooden floor"])
            self.assertEqual(node.negative_prompt, ["crowded background", "messy room"])
            self.assertEqual(node.renderers, {})

    def test_migrate_action_tags_command_writes_structured_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            action_dir = root / "legacy_action"
            action_dir.mkdir()
            (action_dir / "tags.txt").write_text(
                """
(soles detailed:1.2,toenails), presenting toes, toes focus, close up
=
origin_uc, bad feet, extra toes
node_background, flower field
gen_json, {"sampler": "ignored_for_action"}
""".strip(),
                encoding="utf-8",
            )
            output = action_dir / "meta.yaml"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = legacy_migration_main(
                    [
                        "migrate-action-tags",
                        str(action_dir),
                        "--id",
                        "migrated_action",
                        "--character-scope",
                        "foot_detail",
                        "--output",
                        str(output),
                    ]
                )
            data = json.loads(stdout.getvalue())
            node = NodeReader().read(output)

            self.assertEqual(exit_code, 0)
            self.assertEqual(data["id"], "migrated_action")
            self.assertTrue(output.exists())
            self.assertEqual(node.kind, "action")
            self.assertEqual(node.id, "migrated_action")
            self.assertEqual(
                node.tags["action"],
                [
                    "(soles detailed:1.2,toenails)",
                    "presenting toes",
                    "toes focus",
                    "close up",
                ],
            )
            self.assertEqual(node.negative_prompt, ["bad feet, extra toes"])
            self.assertEqual(node.character_scope, "foot_detail")
            self.assertEqual(node.renderers, {})

    def test_migrate_character_tags_command_writes_structured_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character_dir = root / "legacy_character"
            character_dir.mkdir()
            (character_dir / "tags.txt").write_text(
                """
tachibana_kanade,angel_beats!
yellow_eyes,grey_hair,hairband
blazer,pleated_skirt,thighhighs
shirasaya
=
leg_wear, stirrup legwear|toeless legwear
shoes, shoes|boots|loafers
""".strip(),
                encoding="utf-8",
            )
            output = character_dir / "meta.yaml"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = legacy_migration_main(
                    [
                        "migrate-character-tags",
                        str(character_dir),
                        "--id",
                        "migrated_character",
                        "--variant",
                        "school_uniform",
                        "--output",
                        str(output),
                    ]
                )
            data = json.loads(stdout.getvalue())
            node = NodeReader().read(output)

            self.assertEqual(exit_code, 0)
            self.assertEqual(data["id"], "migrated_character")
            self.assertTrue(output.exists())
            self.assertEqual(node.kind, "character")
            self.assertEqual(node.id, "migrated_character")
            self.assertEqual(node.character_id, "tachibana_kanade")
            self.assertEqual(node.variant, "school_uniform")
            self.assertEqual(node.tags["character"], ["tachibana_kanade"])
            self.assertEqual(node.tags["copyright"], ["angel_beats!"])
            self.assertEqual(node.tags["eyes"], ["yellow_eyes"])
            self.assertEqual(node.tags["hair"], ["grey_hair"])
            self.assertEqual(node.tags["headwear"], ["hairband"])
            self.assertEqual(node.tags["upper_clothes"], ["blazer"])
            self.assertEqual(node.tags["lower_clothes"], ["pleated_skirt"])
            self.assertEqual(node.tags["legwear"], ["thighhighs"])
            self.assertEqual(node.tags["weapons"], ["shirasaya"])
            self.assertEqual(node.renderers, {})

    def test_audit_legacy_tags_command_writes_report_without_node_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            action_root = root / "legacy_actions"
            action_root.mkdir()
            clean_action = action_root / "foot_detail"
            clean_action.mkdir()
            (clean_action / "tags.txt").write_text(
                """
foot focus, close-up
=
uc, bad feet
""".strip(),
                encoding="utf-8",
            )
            review_action = action_root / "default_with_character_tags"
            review_action.mkdir()
            (review_action / "tags.txt").write_text(
                """
standing, looking at viewer, blue eyes, long hair
=
node_background, flower field
""".strip(),
                encoding="utf-8",
            )
            report_path = root / "audit_report.yaml"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = legacy_migration_main(
                    [
                        "audit-legacy-tags",
                        str(action_root),
                        "--kind",
                        "action",
                        "--output",
                        str(report_path),
                    ]
                )
            data = json.loads(stdout.getvalue())
            report = yaml.safe_load(report_path.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertTrue(report_path.exists())
            self.assertEqual(data["schema"], "tags-machine-core.legacy-tags-audit/v1")
            self.assertEqual(data["summary"]["total"], 2)
            self.assertEqual(data["summary"]["ok"], 1)
            self.assertEqual(data["summary"]["needs_review"], 1)
            self.assertEqual(
                data["summary"]["issue_counts"]["action_default_scope_needs_review"],
                1,
            )
            self.assertEqual(
                data["summary"]["issue_counts"]["action_maybe_contains_character_tags"],
                1,
            )
            self.assertEqual(
                data["summary"]["issue_counts"]["action_legacy_extension_archived"],
                1,
            )
            items_by_id = {item["node_id"]: item for item in data["items"]}
            self.assertEqual(items_by_id["foot_detail"]["status"], "ok")
            self.assertEqual(items_by_id["foot_detail"]["character_scope"], "foot_detail")
            self.assertEqual(items_by_id["default_with_character_tags"]["status"], "needs_review")
            self.assertEqual(
                items_by_id["default_with_character_tags"]["character_scope"],
                "default",
            )
            self.assertEqual(report["summary"], data["summary"])
            self.assertFalse((clean_action / "meta.yaml").exists())
            self.assertFalse((review_action / "meta.yaml").exists())

    def test_plan_legacy_tags_migration_command_writes_plan_without_node_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            style_root = root / "legacy_styles"
            style_root.mkdir()
            style_dir = style_root / "anime_style"
            style_dir.mkdir()
            (style_dir / "tags.txt").write_text(
                """
soft anime style,
=
gen_json, {"reference_image_multiple": ["abc"], "reference_strength_multiple": [0.2]}
""".strip(),
                encoding="utf-8",
            )
            output_root = root / "migrated"
            plan_path = root / "migration_plan.yaml"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = legacy_migration_main(
                    [
                        "plan-legacy-tags-migration",
                        str(style_root),
                        "--kind",
                        "artist",
                        "--output-root",
                        str(output_root),
                        "--output",
                        str(plan_path),
                    ]
                )
            data = json.loads(stdout.getvalue())
            plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(data["schema"], "tags-machine-core.legacy-tags-migration-plan/v1")
            self.assertEqual(data["kind"], "artist")
            self.assertEqual(data["summary"]["total"], 1)
            self.assertEqual(data["summary"]["ready"], 1)
            self.assertEqual(data["summary"]["issue_counts"]["artist_reference_params_present"], 1)
            item = data["items"][0]
            self.assertEqual(item["node_id"], "anime_style")
            self.assertEqual(item["safe_node_dir"], "anime_style")
            self.assertEqual(item["migration_status"], "ready")
            self.assertEqual(
                item["target_file"],
                str(output_root / "nodes" / "artists" / "anime_style" / "node.yaml"),
            )
            self.assertEqual(plan["summary"], data["summary"])
            self.assertTrue(plan_path.exists())
            self.assertFalse((style_dir / "node.yaml").exists())
            self.assertFalse((output_root / "nodes" / "artists" / "anime_style" / "node.yaml").exists())

    def test_apply_legacy_tags_migration_command_writes_ready_nodes_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character_root = root / "legacy_characters"
            character_root.mkdir()
            ready_character = character_root / "ready_character"
            ready_character.mkdir()
            (ready_character / "tags.txt").write_text(
                """
ready_character,ready_copyright
blue_eyes,short_hair,jacket
""".strip(),
                encoding="utf-8",
            )
            review_character = character_root / "needs_review"
            review_character.mkdir()
            (review_character / "tags.txt").write_text(
                """
review_character,review_copyright
signature_motif
""".strip(),
                encoding="utf-8",
            )
            output_root = root / "migrated"
            report_path = root / "apply_report.yaml"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = legacy_migration_main(
                    [
                        "apply-legacy-tags-migration",
                        str(character_root),
                        "--kind",
                        "character",
                        "--output-root",
                        str(output_root),
                        "--output",
                        str(report_path),
                    ]
                )
            data = json.loads(stdout.getvalue())
            report = yaml.safe_load(report_path.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 0)
            self.assertEqual(data["schema"], "tags-machine-core.legacy-tags-migration-apply/v1")
            self.assertEqual(data["summary"]["written"], 1)
            self.assertEqual(data["summary"]["skipped"], 1)
            self.assertEqual(
                data["summary"]["skip_reasons"],
                {"migration_status:needs_review": 1},
            )
            ready_output = output_root / "nodes" / "characters" / "ready_character" / "meta.yaml"
            review_output = output_root / "nodes" / "characters" / "needs_review" / "meta.yaml"
            self.assertTrue(ready_output.exists())
            self.assertFalse(review_output.exists())
            migrated_node = NodeReader().read(ready_output)
            self.assertEqual(migrated_node.kind, "character")
            self.assertEqual(migrated_node.tags["character"], ["ready_character"])
            self.assertEqual(migrated_node.tags["eyes"], ["blue_eyes"])
            self.assertEqual(report["summary"], data["summary"])
            self.assertFalse((ready_character / "meta.yaml").exists())
            self.assertFalse((review_character / "meta.yaml").exists())

    def test_validate_node_tree_command_reports_invalid_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            action_dir = root / "nodes" / "actions" / "missing_scope"
            action_dir.mkdir(parents=True)
            (action_dir / "meta.yaml").write_text(
                """
schema: tags-machine.action/v1
kind: action
id: missing_scope
tags:
  action:
    - foot focus
""".strip(),
                encoding="utf-8",
            )
            style_dir = root / "nodes" / "styles" / "missing_renderer"
            style_dir.mkdir(parents=True)
            (style_dir / "node.yaml").write_text(
                """
schema: tags-machine.artist/v1
kind: artist
id: missing_renderer
tags:
  artist:
    - soft anime style
""".strip(),
                encoding="utf-8",
            )
            report_path = root / "node_validation.yaml"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "validate-node-tree",
                        str(root / "nodes"),
                        "--output",
                        str(report_path),
                    ]
                )
            data = json.loads(stdout.getvalue())
            report = yaml.safe_load(report_path.read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 2)
            self.assertFalse(data["valid"])
            self.assertEqual(data["result"], "fail")
            self.assertEqual(data["summary"]["total_files"], 2)
            self.assertEqual(data["summary"]["fail_count"], 2)
            self.assertEqual(data["summary"]["issue_counts"]["action_missing_character_scope"], 1)
            self.assertEqual(data["summary"]["issue_counts"]["artist_missing_renderers"], 1)
            self.assertEqual(report["summary"], data["summary"])


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
