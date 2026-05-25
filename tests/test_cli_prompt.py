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
from tags_machine_core.contracts import GenerationResult
from tags_machine_core.nodes import NodeReader
from tags_machine_core.services import GenerationService
from tags_machine_core.verification import verify_acceptance_suite


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


def _write_style_node(root: Path) -> Path:
    style = root / "style"
    style.mkdir()
    (style / "node.yaml").write_text(
        """
schema: tags-machine.style/v1
kind: style
id: prompt_style
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
      reference_information_extracted_multiple:
        - 0.6
      director_reference_images:
        - director-abc
""".strip(),
        encoding="utf-8",
    )
    return style


class CliPromptTest(unittest.TestCase):
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
novelai:
  base_url: "http://novelai.local"
  access_token_env: "NAI_ACCESS_TOKEN"
  timeout: 30
  retry: 1
""".strip(),
            encoding="utf-8",
        )
        return config

    def test_run_prompt_dry_run_builds_prompt_bundle_and_novelai_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            style = _write_style_node(root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "run-prompt",
                        "--dry-run",
                        "--full",
                        "--prompt",
                        "akemi homura, bare soles, foot focus",
                        "--negative",
                        "bad feet",
                        "--style-node",
                        str(style),
                        "--seed",
                        "789",
                        "--width",
                        "832",
                        "--height",
                        "1216",
                        "--nt",
                        "3",
                        "--params-json",
                        '{"scale": 6.0}',
                    ]
                )

            data = json.loads(stdout.getvalue())
            bundle = data["prompt_bundle"]
            request = data["render_request"]
            self.assertEqual(exit_code, 0)
            self.assertEqual(data["schema"], "tags-machine-core.run-prompt-result/v1")
            self.assertTrue(data["dry_run"])
            self.assertEqual(
                bundle["prompt"]["positive"],
                "akemi homura, bare soles, foot focus",
            )
            self.assertEqual(bundle["prompt"]["negative"], "bad feet")
            self.assertEqual(bundle["meta"]["style_ref"], "prompt_style")
            self.assertEqual(bundle["meta"]["composition"]["included_character_sections"], [])
            self.assertEqual(request["backend"], "novelai")
            self.assertEqual(request["seed"], 789)
            self.assertEqual(request["size"], {"width": 832, "height": 1216})
            self.assertEqual(request["params"]["n_samples"], 3)
            self.assertEqual(request["params"]["scale"], 6.0)
            self.assertEqual(request["params"]["steps"], 30)
            self.assertEqual(request["params"]["reference_image_multiple"], ["abc"])
            self.assertEqual(request["params"]["reference_strength_multiple"], [0.25])
            self.assertEqual(request["params"]["reference_information_extracted_multiple"], [0.6])
            self.assertEqual(request["params"]["director_reference_images"], ["director-abc"])
            self.assertIn("style prefix", request["prompt"])
            self.assertIn("akemi homura, bare soles, foot focus", request["prompt"])
            self.assertIn("anime style", request["prompt"])
            self.assertIn("{best quality}", request["prompt"])
            self.assertIn("style suffix", request["prompt"])
            self.assertIn("bad feet", request["negative_prompt"])
            self.assertIn("lowres", request["negative_prompt"])
            self.assertIn("bad anatomy", request["negative_prompt"])

    def test_run_prompt_reads_prompt_file_and_style_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            style = _write_style_node(root)
            prompt_file = root / "prompt.txt"
            prompt_file.write_text("akemi homura, hand focus", encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "run-prompt",
                        "--dry-run",
                        "--prompt-file",
                        str(prompt_file),
                        "--artist",
                        "artist_alias",
                        "--style-node",
                        str(style),
                    ]
                )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(data["prompt_bundle"]["prompt"]["positive"], "akemi homura, hand focus")
            self.assertEqual(data["prompt_bundle"]["meta"]["style_ref"], "artist_alias")
            self.assertEqual(data["render_request"]["meta"]["style_ref"], "artist_alias")

    def test_run_prompt_executes_novelai_and_records_generation_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            style = _write_style_node(root)
            config = self._write_config(root)
            output_dir = root / "custom_outputs"

            with (
                patch.dict("os.environ", {"NAI_ACCESS_TOKEN": "token"}),
                patch("tags_machine_core.execution.NovelAIClient") as client_cls,
            ):
                client = client_cls.return_value
                client.generate_images.return_value = [
                    SimpleNamespace(filename="nai_result", content=b"image-bytes")
                ]
                client.build_payload.return_value = {
                    "input": "style prefix, akemi homura, foot focus",
                    "parameters": {"seed": 111, "n_samples": 2},
                }

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "run-prompt",
                            "--prompt",
                            "akemi homura, foot focus",
                            "--style-node",
                            str(style),
                            "--config",
                            str(config),
                            "--output-dir",
                            str(output_dir),
                            "--seed",
                            "111",
                            "--nt",
                            "2",
                            "--format",
                            "webp",
                        ]
                    )

            data = json.loads(stdout.getvalue())
            result = data["generation_result"]
            request = data["render_request"]
            self.assertEqual(exit_code, 0)
            client_cls.assert_called_once_with(
                access_token="token",
                base_url="http://novelai.local",
                timeout=30,
                retry=1,
            )
            client.generate_images.assert_called_once()
            called_request = client.generate_images.call_args.args[0]
            self.assertEqual(called_request.params["n_samples"], 2)
            self.assertEqual(request["params"]["n_samples"], 2)
            self.assertEqual(result["backend"], "novelai")
            self.assertEqual(result["request_body"]["parameters"]["n_samples"], 2)
            self.assertEqual(len(result["images"]), 1)
            saved_path = Path(result["images"][0]["path"])
            self.assertEqual(saved_path.parent, output_dir)
            self.assertEqual(saved_path.suffix, ".webp")
            self.assertEqual(saved_path.read_bytes(), b"image-bytes")
            self.assertIn("error", result["png_info"]["images"][0])

    def test_run_prompt_uses_unified_execution_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            style = _write_style_node(root)
            config = self._write_config(root)
            output_dir = root / "custom_outputs"

            with patch("tags_machine_core.cli._execute_render_request") as executor:
                executor.return_value = GenerationResult(
                    backend="novelai",
                    request_body={"parameters": {"n_samples": 2}},
                )

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "run-prompt",
                            "--prompt",
                            "akemi homura, foot focus",
                            "--style-node",
                            str(style),
                            "--config",
                            str(config),
                            "--output-dir",
                            str(output_dir),
                            "--seed",
                            "111",
                            "--nt",
                            "2",
                            "--format",
                            "webp",
                        ]
                    )

            data = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(data["generation_result"]["backend"], "novelai")
            executor.assert_called_once()
            called_config, called_request = executor.call_args.args
            self.assertEqual(called_config.novelai.base_url, "http://novelai.local")
            self.assertEqual(called_request.backend, "novelai")
            self.assertEqual(called_request.params["n_samples"], 2)
            self.assertEqual(executor.call_args.kwargs["output_dir"], str(output_dir))
            self.assertEqual(executor.call_args.kwargs["image_format"], "webp")
            self.assertIs(executor.call_args.kwargs["allow_experimental_backend"], False)

    def test_generate_uses_unified_execution_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._write_config(root)
            output_dir = root / "generated_outputs"

            with patch("tags_machine_core.cli._execute_render_request") as executor:
                executor.return_value = GenerationResult(
                    backend="novelai",
                    request_body={"parameters": {"seed": 222}},
                )

                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "generate",
                            "--prompt",
                            "akemi homura",
                            "--config",
                            str(config),
                            "--output-dir",
                            str(output_dir),
                            "--seed",
                            "222",
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
            self.assertEqual(called_request.seed, 222)
            self.assertEqual(executor.call_args.kwargs["output_dir"], str(output_dir))
            self.assertEqual(executor.call_args.kwargs["image_format"], "png")
            self.assertIs(executor.call_args.kwargs["allow_experimental_backend"], False)

    def test_archive_novelai_acceptance_prompt_builds_core_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            style = _write_style_node(root)
            reader = NodeReader()
            service = GenerationService()
            prompt = "akemi homura, bare soles, foot focus"
            bundle = service.compose_full_prompt(prompt=prompt, style_ref="prompt_style")
            request = service.build_novelai_request(
                bundle,
                seed=789,
                width=832,
                height=1216,
                style=reader.read(style),
                params={"n_samples": 2},
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
                        "archive-novelai-acceptance-prompt",
                        "--case-id",
                        "default_action_prompt_001",
                        "--output-dir",
                        str(root / "acceptance"),
                        "--legacy-source",
                        str(legacy),
                        "--legacy-image",
                        str(legacy_image),
                        "--prompt",
                        prompt,
                        "--style-node",
                        str(style),
                        "--seed",
                        "789",
                        "--width",
                        "832",
                        "--height",
                        "1216",
                        "--nt",
                        "2",
                        "--generation-result",
                        str(generation_result),
                        "--required-case",
                        "default_action",
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
            generated_request = json.loads(render_request_path.read_text(encoding="utf-8"))
            generated_bundle = json.loads(prompt_bundle_path.read_text(encoding="utf-8"))
            generated_result = json.loads(
                (case_dir / "core" / "generation_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(generated_request["backend"], "novelai")
            self.assertEqual(generated_request["params"]["n_samples"], 2)
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
            self.assertEqual(generated_bundle["prompt"]["positive"], prompt)
            self.assertEqual(
                archive["record"]["core"]["prompt_bundle_path"],
                "core/prompt_bundle.json",
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

    def test_run_prompt_and_acceptance_prompt_archive_build_identical_core_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            style = _write_style_node(root)
            prompt_file = root / "agent_prompt.txt"
            prompt_file.write_text(
                "akemi homura, bare soles, foot focus, soles toward viewer",
                encoding="utf-8",
            )

            dry_run_stdout = io.StringIO()
            with redirect_stdout(dry_run_stdout):
                dry_run_exit = main(
                    [
                        "run-prompt",
                        "--dry-run",
                        "--full",
                        "--prompt-file",
                        str(prompt_file),
                        "--negative",
                        "bad feet",
                        "--artist",
                        "artist_alias",
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
            dry_run = json.loads(dry_run_stdout.getvalue())

            legacy = root / "legacy_request.json"
            legacy.write_text(
                json.dumps(dry_run["render_request"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            archive_stdout = io.StringIO()
            with redirect_stdout(archive_stdout):
                archive_exit = main(
                    [
                        "archive-novelai-acceptance-prompt",
                        "--case-id",
                        "default_action_agent_prompt_001",
                        "--output-dir",
                        str(root / "acceptance"),
                        "--legacy-source",
                        str(legacy),
                        "--prompt-file",
                        str(prompt_file),
                        "--negative",
                        "bad feet",
                        "--artist",
                        "artist_alias",
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
                        "--required-case",
                        "default_action",
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

            self.assertEqual(dry_run_exit, 0)
            self.assertEqual(archive_exit, 0)
            self.assertEqual(archive["result"], "pass")
            self.assertEqual(
                _without_runtime_fields(archived_bundle),
                _without_runtime_fields(dry_run["prompt_bundle"]),
            )
            self.assertEqual(archived_request, dry_run["render_request"])
            self.assertEqual(archived_bundle["meta"]["composition"]["character_scope"], None)
            self.assertEqual(archived_bundle["meta"]["composition"]["included_character_sections"], [])
            self.assertEqual(archived_request["params"]["n_samples"], 2)
            self.assertEqual(archived_request["params"]["cfg_rescale"], 0.15)
            self.assertEqual(archived_request["meta"]["style_ref"], "artist_alias")


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
