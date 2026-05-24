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

from tags_machine_core.cli import main
from tags_machine_core.nodes import NodeReader


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
                        "12": {"inputs": {"cfg": 5.0}},
                        "17": {"inputs": {"text": ""}},
                    }
                ),
                encoding="utf-8",
            )
            (style / "node.yaml").write_text(
                """
schema: tags-machine.style/v1
kind: style
id: comfy_workflow_style
renderers:
  comfyui:
    workflow: portrait_workflow
    workflow_path: workflows/portrait.json
    checkpoint: anime_comfy.safetensors
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
                        "--style-node",
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
                "akemi homura, bare soles, foot focus",
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

            with patch("tags_machine_core.cli.ComfyUIClient") as client_cls:
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
                            "--client-id",
                            "client-1",
                            "--comfyui-no-wait",
                        ]
                    )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            client_cls.assert_called_once_with(base_url="http://comfy.local", timeout=30)
            client.queue_prompt.assert_called_once()
            self.assertEqual(client.queue_prompt.call_args.kwargs["client_id"], "client-1")
            client.generate_images.assert_not_called()
            self.assertEqual(data["backend"], "comfyui")
            self.assertEqual(data["images"], [])
            self.assertEqual(data["request_body"]["client_id"], "client-1")
            self.assertEqual(data["png_info"]["comfyui"]["prompt_id"], "abc123")

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

            with patch("tags_machine_core.cli.ComfyUIClient") as client_cls:
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
            self.assertEqual(saved_path.read_bytes(), image_bytes)
            self.assertEqual(data["images"][0]["meta"]["node_id"], "7")
            self.assertEqual(data["images"][0]["meta"]["image_type"], "output")
            png_info = data["png_info"]["images"][0]
            self.assertEqual(png_info["parameters"]["prompt"], "akemi homura")
            self.assertEqual(png_info["parameters"]["seed"], 222)
            self.assertEqual(png_info["png_text"]["Source"], "ComfyUI")

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

            with patch("tags_machine_core.cli.SDClient") as client_cls:
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

            with patch("tags_machine_core.cli.SDClient") as client_cls:
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
                exit_code = main(
                    [
                        "migrate-style-tags",
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
            self.assertEqual(node.kind, "style")
            self.assertEqual(node.id, "migrated_style")
            self.assertEqual(node.tags["style"], ["style prefix", "style suffix, best quality"])
            self.assertFalse(node.renderers["novelai"]["include_common_tags"])
            self.assertEqual(node.renderers["novelai"]["negative_prompt"], ["lowres, bad anatomy"])
            self.assertEqual(node.renderers["novelai"]["after_negative_prompt"], ["extra fingers"])
            self.assertEqual(node.renderers["novelai"]["params"]["reference_image_multiple"], ["abc"])
            self.assertEqual(node.renderers["novelai"]["params"]["reference_strength_multiple"], [0.2])


if __name__ == "__main__":
    unittest.main()
