import io
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from tags_machine_core.cli import main
from tags_machine_core.contracts import PromptBundle
from tags_machine_core.verification import (
    archive_acceptance_case,
    build_acceptance_record,
    build_composer_evaluation_report,
    build_image_comparison_report,
    compare_render_parameters,
    normalize_render_parameters,
    read_png_dimensions,
    read_image_parameters,
    run_core_verification,
    verify_acceptance_record,
    verify_acceptance_suite,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _write_png_with_text(path: Path, chunks: dict[str, str]) -> None:
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(
        _png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0),
        )
    )
    for key, value in chunks.items():
        png.extend(_png_chunk(b"tEXt", key.encode("latin-1") + b"\x00" + value.encode("utf-8")))
    png.extend(_png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")))
    png.extend(_png_chunk(b"IEND", b""))
    path.write_bytes(bytes(png))


def _sample_parameters(reference: str = "base64-reference") -> dict:
    return {
        "prompt": "akemi homura, foot focus",
        "negative_prompt": "bad feet",
        "model": "nai-diffusion-4-5-full",
        "width": 832,
        "height": 1216,
        "scale": 5.0,
        "sampler": "k_euler",
        "steps": 28,
        "seed": 123,
        "cfg_rescale": 0.0,
        "noise_schedule": "native",
        "reference_image_multiple": [reference],
        "reference_strength_multiple": [0.2],
        "reference_information_extracted_multiple": [1.0],
        "director_reference_images": ["director-image"],
        "v4_prompt": {
            "use_coords": False,
            "use_order": False,
            "caption": {"base_caption": "akemi homura, foot focus", "char_captions": []},
        },
        "v4_negative_prompt": {
            "use_coords": False,
            "use_order": False,
            "caption": {"base_caption": "bad feet", "char_captions": []},
        },
        "signed_hash": "ignored",
    }


def _minimum_case_parameters(case_id: str) -> dict:
    params = _sample_parameters()
    if case_id.startswith("default_action"):
        params["reference_image_multiple"] = []
        params["reference_strength_multiple"] = []
        params["reference_information_extracted_multiple"] = []
        params["director_reference_images"] = []
    if case_id.startswith("hand_detail"):
        prompt = "akemi homura, hand focus, reaching hand"
        negative = "bad hands"
        params["prompt"] = prompt
        params["negative_prompt"] = negative
        params["v4_prompt"]["caption"]["base_caption"] = prompt
        params["v4_negative_prompt"]["caption"]["base_caption"] = negative
    return params


def _prompt_bundle_fixture(
    composition: dict | None = None,
    *,
    prompt: str = "akemi homura, foot focus",
    negative: str = "bad feet",
    meta_extra: dict | None = None,
) -> dict:
    composition = composition or {
        "character_scope": "foot_detail",
        "included_character_sections": ["character", "feet"],
        "suppressed_character_sections": ["eyes", "upper_clothes"],
    }
    meta = {
        "character_ref": "homura",
        "action_ref": "foot_closeup",
        "style_ref": "test_style",
        "composer_type": "script",
        "composer_version": "v1",
        "composition": composition,
        "source_nodes": ["homura", "foot_closeup"],
    }
    if meta_extra:
        meta.update(meta_extra)
    return {
        "schema": "tags-machine-core.prompt-bundle/v1",
        "prompt": {
            "positive": prompt,
            "negative": negative,
        },
        "meta": meta,
        "cache": {
            "cacheable": True,
            "cache_key": "sha256:test-fixture",
            "cache_hit": False,
        },
        "created_at": "2026-05-25T00:00:00+00:00",
    }


class VerificationTest(unittest.TestCase):
    def test_build_composer_evaluation_report_records_scope_sections(self):
        bundle = PromptBundle.model_validate(_prompt_bundle_fixture())

        report = build_composer_evaluation_report(
            case_id="foot_detail_homura_001",
            prompt_bundle=bundle,
            legacy_prompt=(
                "akemi homura, long black hair, purple eyes, "
                "school uniform, bare soles, foot focus"
            ),
        )

        self.assertEqual(report["schema"], "tags-machine-core.composer-evaluation/v1")
        self.assertEqual(report["case_id"], "foot_detail_homura_001")
        self.assertEqual(report["composition"]["character_scope"], "foot_detail")
        self.assertIn("eyes", report["composition"]["suppressed_character_sections"])
        self.assertIn("upper_clothes", report["composition"]["suppressed_character_sections"])
        self.assertEqual(report["visual"]["result"], "pending")
        self.assertTrue(report["intentional_differences"])
        self.assertEqual(
            report["intentional_differences"][0]["reason"],
            "局部镜头按统一 composer policy 过滤无关角色 section",
        )

    def test_run_core_verification_dry_run_lists_no_network_gate(self):
        result = run_core_verification(cwd=PROJECT_ROOT, dry_run=True)

        labels = [item["label"] for item in result["commands"]]
        self.assertEqual(result["schema"], "tags-machine-core.core-verification/v1")
        self.assertEqual(result["result"], "dry_run")
        self.assertTrue(result["match"])
        self.assertEqual(
            labels,
            [
                "compileall",
                "unittest_discover",
                "validate_example_nodes",
                "fixture_acceptance_suite",
                "git_diff_check",
            ],
        )
        self.assertTrue(
            any(
                "verify-acceptance-suite" in item["command_text"]
                and "--require-minimum-set" in item["command_text"]
                for item in result["commands"]
            )
        )

    def test_run_core_verification_reports_failed_command(self):
        calls: list[list[str]] = []

        def runner(command, cwd):
            calls.append(list(command))
            returncode = 1 if len(calls) == 2 else 0
            return SimpleNamespace(
                returncode=returncode,
                stdout="ok" if returncode == 0 else "unit test failure",
                stderr="",
            )

        result = run_core_verification(cwd=PROJECT_ROOT, runner=runner)

        self.assertFalse(result["match"])
        self.assertEqual(result["result"], "fail")
        self.assertEqual(result["summary"]["total"], 5)
        self.assertEqual(result["summary"]["fail_count"], 1)
        self.assertEqual(result["commands"][1]["label"], "unittest_discover")
        self.assertEqual(result["commands"][1]["status"], "fail")
        self.assertIn("unit test failure", result["commands"][1]["stdout_tail"])
        self.assertEqual(len(calls), 5)

    def test_cli_verify_core_dry_run(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["verify-core", "--dry-run"])

        data = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(data["result"], "dry_run")
        self.assertEqual(data["commands"][0]["label"], "compileall")

    def test_read_png_parameters_keeps_full_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.png"
            params = _sample_parameters()
            _write_png_with_text(
                path,
                {
                    "Comment": json.dumps(params),
                    "Source": "NovelAI V4.5",
                    "Software": "NovelAI",
                },
            )

            data = read_image_parameters(path)

            self.assertEqual(data["parameters"]["prompt"], "akemi homura, foot focus")
            self.assertIn("v4_prompt", data["parameters"])
            self.assertEqual(data["parameters"]["reference_image_multiple"], ["base64-reference"])
            self.assertEqual(data["png_text"]["Source"], "NovelAI V4.5")

    def test_read_png_dimensions_reads_ihdr_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.png"
            _write_png_with_text(path, {"Comment": json.dumps(_sample_parameters())})

            self.assertEqual(read_png_dimensions(path), {"width": 1, "height": 1})

    def test_normalize_render_parameters_summarizes_reference_images(self):
        normalized = normalize_render_parameters(
            {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
        )

        reference = normalized["parameters"]["reference_image_multiple"][0]
        self.assertEqual(reference["type"], "string")
        self.assertEqual(reference["chars"], len("base64-reference"))
        self.assertIn("sha256", reference)
        self.assertIn("v4_prompt", normalized["parameters"])
        self.assertNotIn("signed_hash", normalized["parameters"])

    def test_compare_render_parameters_accepts_render_request_and_raw_payload(self):
        render_request = {
            "schema": "tags-machine-core.render-request/v1",
            "backend": "novelai",
            "prompt": "akemi homura, foot focus",
            "negative_prompt": "bad feet",
            "model": "nai-diffusion-4-5-full",
            "params": _sample_parameters(),
            "meta": {"action": "generate"},
        }
        raw_payload = {
            "input": "akemi homura, foot focus",
            "model": "nai-diffusion-4-5-full",
            "action": "generate",
            "parameters": _sample_parameters(),
        }

        self.assertEqual(compare_render_parameters(render_request, raw_payload), [])

    def test_compare_render_parameters_accepts_generation_result_request_body(self):
        raw_payload = {
            "input": "akemi homura, foot focus",
            "model": "nai-diffusion-4-5-full",
            "action": "generate",
            "parameters": _sample_parameters(),
        }
        generation_result = {
            "schema": "tags-machine-core.generation-result/v1",
            "backend": "novelai",
            "images": [],
            "request_body": raw_payload,
            "cache_hit": False,
        }

        self.assertEqual(compare_render_parameters(raw_payload, generation_result), [])

    def test_compare_render_parameters_accepts_png_comment_without_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.png"
            _write_png_with_text(
                path,
                {
                    "Comment": json.dumps(_sample_parameters()),
                    "Source": "NovelAI V4.5",
                },
            )
            raw_payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }

            png_parameters = read_image_parameters(path)

            self.assertEqual(compare_render_parameters(png_parameters, raw_payload), [])

    def test_compare_render_parameters_reports_reference_differences(self):
        left = {"parameters": _sample_parameters(reference="left-reference")}
        right = {"parameters": _sample_parameters(reference="rght-reference")}

        diffs = compare_render_parameters(left, right)

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].path, "$.parameters.reference_image_multiple[0].sha256")

    def test_compare_render_parameters_reports_director_reference_differences(self):
        left_params = _sample_parameters()
        right_params = _sample_parameters()
        left_params["director_reference_images"] = ["left-director"]
        right_params["director_reference_images"] = ["rght-director"]

        diffs = compare_render_parameters(
            {"parameters": left_params},
            {"parameters": right_params},
        )

        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].path, "$.parameters.director_reference_images[0].sha256")

    def test_cli_compare_render_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            left = Path(tmp) / "left.json"
            right = Path(tmp) / "right.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            left.write_text(json.dumps(payload), encoding="utf-8")
            right.write_text(json.dumps(payload), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["compare-render-params", str(left), str(right)])

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertTrue(data["match"])
            self.assertEqual(data["diff_count"], 0)

    def test_cli_compare_render_params_accepts_generation_result_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_image = root / "legacy.png"
            generation_result = root / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            _write_png_with_text(legacy_image, {"Comment": json.dumps(_sample_parameters())})
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [],
                        "request_body": payload,
                        "cache_hit": False,
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "compare-render-params",
                        str(legacy_image),
                        str(generation_result),
                        "--show-normalized",
                    ]
                )

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertTrue(data["match"])
            self.assertEqual(data["diff_count"], 0)
            self.assertIn("reference_image_multiple", data["left_normalized"]["parameters"])

    def test_build_image_comparison_report_compares_png_and_generation_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_image = root / "legacy.png"
            core_image = root / "core.png"
            generation_result = root / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            _write_png_with_text(legacy_image, {"Comment": json.dumps(_sample_parameters())})
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [
                            {
                                "path": "core.png",
                                "filename": "core.png",
                                "meta": {"index": 0},
                            }
                        ],
                        "request_body": payload,
                        "png_info": {
                            "images": [
                                {
                                    "path": "core.png",
                                    "parameters": _sample_parameters(),
                                }
                            ]
                        },
                        "cache_hit": False,
                    }
                ),
                encoding="utf-8",
            )

            report = build_image_comparison_report(
                legacy_image,
                generation_result,
                visual_result="pass",
                visual_notes=["subject/action/camera/style checked"],
            )

            self.assertTrue(report["match"])
            self.assertTrue(report["acceptance_ready"])
            self.assertEqual(report["parameter_diff"]["diff_count"], 0)
            self.assertEqual(report["core_request_vs_png"]["diff_count"], 0)
            self.assertEqual(report["legacy_image"]["dimensions"], {"width": 1, "height": 1})
            self.assertEqual(report["core_image"]["dimensions"], {"width": 1, "height": 1})
            self.assertEqual(
                report["legacy_image"]["sha256"],
                hashlib.sha256(legacy_image.read_bytes()).hexdigest(),
            )
            self.assertEqual(report["generation_result"]["selected_core_image"], str(core_image))
            self.assertEqual(report["visual_check"]["result"], "pass")
            self.assertEqual(
                report["parameter_diff"]["left_normalized"]["parameters"][
                    "reference_image_multiple"
                ][0]["chars"],
                len("base64-reference"),
            )

    def test_cli_compare_image_result_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_image = root / "legacy.png"
            core_image = root / "core.png"
            generation_result = root / "generation_result.json"
            report_path = root / "report.yaml"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            _write_png_with_text(legacy_image, {"Comment": json.dumps(_sample_parameters())})
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [{"path": str(core_image), "filename": "core.png"}],
                        "request_body": payload,
                        "cache_hit": False,
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "compare-image-result",
                        "--legacy-image",
                        str(legacy_image),
                        "--core-generation-result",
                        str(generation_result),
                        "--visual-result",
                        "pending",
                        "--visual-note",
                        "waiting for manual visual check",
                        "--output",
                        str(report_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertTrue(data["match"])
            self.assertFalse(data["acceptance_ready"])
            self.assertEqual(data["visual_check"]["result"], "pending")
            self.assertTrue(report_path.exists())

    def test_cli_inspect_image_params_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.png"
            _write_png_with_text(
                path,
                {
                    "Comment": json.dumps(_sample_parameters()),
                    "Source": "NovelAI V4.5",
                    "Software": "NovelAI",
                },
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["inspect-image-params", str(path), "--normalized"])

            self.assertEqual(exit_code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data["action"], "generate")
            self.assertEqual(data["model"], "nai-diffusion-4-5-full")
            self.assertIn("reference_image_multiple", data["parameters"])
            self.assertIn("sha256", data["parameters"]["reference_image_multiple"][0])

    def test_build_acceptance_record_with_prompt_bundle_composition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            bundle = root / "bundle.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            bundle.write_text(
                json.dumps(
                    _prompt_bundle_fixture(
                        {
                            "character_scope": "foot_detail",
                            "included_character_sections": ["character", "feet"],
                            "suppressed_character_sections": ["eyes", "upper_clothes"],
                        }
                    )
                ),
                encoding="utf-8",
            )

            record = build_acceptance_record(
                case_id="foot_detail_homura_001",
                legacy_source=legacy,
                core_source=core,
                prompt_bundle=bundle,
                notes=["sample acceptance"],
            )

            self.assertEqual(record["result"], "pass")
            self.assertTrue(record["diff"]["normalized_equal"])
            self.assertEqual(record["diff"]["unapproved_diff_count"], 0)
            self.assertEqual(record["composition"]["character_scope"], "foot_detail")
            self.assertEqual(record["prompt_bundle_contract_evidence"]["result"], "pass")
            self.assertEqual(record["notes"], ["sample acceptance"])

    def test_verify_acceptance_record_fails_prompt_bundle_contract_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            bundle = root / "bundle.json"
            record_path = root / "acceptance.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            bundle.write_text(
                json.dumps(
                    _prompt_bundle_fixture(
                        {
                            "character_scope": "foot_detail",
                            "included_character_sections": ["character", "feet"],
                            "suppressed_character_sections": ["eyes", "upper_clothes"],
                        },
                        meta_extra={
                            "shot": {"body_scope": "foot_detail"},
                            "constraints": {"forbidden_parts": ["eyes"]},
                        },
                    )
                ),
                encoding="utf-8",
            )
            record = build_acceptance_record(
                case_id="foot_detail_homura_001",
                legacy_source=legacy,
                core_source=core,
                prompt_bundle=bundle,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            verified = verify_acceptance_record(record_path)

            self.assertFalse(verified["match"])
            self.assertEqual(verified["result"], "fail")
            self.assertEqual(
                verified["prompt_bundle_contract_evidence"]["forbidden_meta_fields"],
                ["shot", "constraints"],
            )

    def test_verify_acceptance_record_fails_prompt_bundle_backend_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            bundle = root / "bundle.json"
            record_path = root / "acceptance.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            bundle_data = _prompt_bundle_fixture(
                {
                    "character_scope": "foot_detail",
                    "included_character_sections": ["character", "feet"],
                    "suppressed_character_sections": ["eyes", "upper_clothes"],
                }
            )
            bundle_data.update(
                {
                    "backend": "novelai",
                    "params": {
                        "v4_prompt": {"caption": {"base_caption": "akemi homura"}},
                        "reference_image_multiple": ["base64-ref"],
                    },
                    "style_payload": {"renderers": {"novelai": {}}},
                }
            )
            bundle.write_text(
                json.dumps(bundle_data),
                encoding="utf-8",
            )
            record = build_acceptance_record(
                case_id="prompt_bundle_backend_leak",
                legacy_source=legacy,
                core_source=core,
                prompt_bundle=bundle,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            verified = verify_acceptance_record(record_path)

            self.assertFalse(verified["match"])
            self.assertEqual(verified["result"], "fail")
            self.assertEqual(verified["prompt_bundle_contract_evidence"]["result"], "fail")
            self.assertEqual(
                verified["prompt_bundle_contract_evidence"]["forbidden_backend_fields"],
                [
                    "$.backend",
                    "$.params",
                    "$.params.v4_prompt",
                    "$.params.reference_image_multiple",
                    "$.style_payload",
                    "$.style_payload.renderers",
                ],
            )

    def test_verify_acceptance_record_fails_incomplete_prompt_bundle_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            bundle = root / "bundle.json"
            record_path = root / "acceptance.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            bundle.write_text(
                json.dumps({"meta": {"composition": {"character_scope": "foot_detail"}}}),
                encoding="utf-8",
            )
            record = build_acceptance_record(
                case_id="prompt_bundle_incomplete_contract",
                legacy_source=legacy,
                core_source=core,
                prompt_bundle=bundle,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            verified = verify_acceptance_record(record_path)

            self.assertFalse(verified["match"])
            evidence = verified["prompt_bundle_contract_evidence"]
            self.assertEqual(evidence["result"], "fail")
            self.assertIn(
                "$.schema must be tags-machine-core.prompt-bundle/v1",
                evidence["contract_errors"],
            )
            self.assertIn("$.prompt must be an object", evidence["contract_errors"])
            self.assertIn(
                "$.meta.composer_type must be one of: agent, legacy, script",
                evidence["contract_errors"],
            )
            self.assertIn(
                "$.meta.composition.included_character_sections must be a list",
                evidence["contract_errors"],
            )

    def test_build_acceptance_record_records_image_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            legacy_image = root / "legacy.png"
            core_image = root / "core.png"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            _write_png_with_text(
                legacy_image,
                {
                    "Comment": json.dumps(_sample_parameters()),
                    "Source": "NovelAI V4.5",
                },
            )
            _write_png_with_text(
                core_image,
                {
                    "Comment": json.dumps(_sample_parameters()),
                    "Source": "NovelAI V4.5",
                },
            )

            record = build_acceptance_record(
                case_id="image_evidence",
                legacy_source=legacy,
                core_source=core,
                legacy_image=legacy_image,
                core_image=core_image,
            )

            legacy_evidence = record["image_evidence"]["legacy"]
            core_evidence = record["image_evidence"]["core"]
            self.assertTrue(legacy_evidence["exists"])
            self.assertEqual(legacy_evidence["bytes"], legacy_image.stat().st_size)
            self.assertEqual(
                legacy_evidence["sha256"],
                hashlib.sha256(legacy_image.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                legacy_evidence["png_info"]["parameters"]["prompt"],
                "akemi homura, foot focus",
            )
            self.assertEqual(core_evidence["png_info"]["png_text"]["Source"], "NovelAI V4.5")

    def test_verify_acceptance_record_recomputes_image_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_dir = root / "acceptance"
            record_dir.mkdir()
            legacy = record_dir / "legacy.json"
            core = record_dir / "core.json"
            image = record_dir / "legacy.png"
            record_path = record_dir / "image_record.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            _write_png_with_text(
                image,
                {
                    "Comment": json.dumps(_sample_parameters()),
                    "Source": "NovelAI V4.5",
                },
            )
            record_path.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.acceptance-record/v1",
                        "case_id": "image_evidence",
                        "legacy": {"source_path": "legacy.json", "image_path": "legacy.png"},
                        "core": {"source_path": "core.json"},
                        "diff": {"whitelist": []},
                    }
                ),
                encoding="utf-8",
            )

            result = verify_acceptance_record(record_path)

            self.assertTrue(result["match"])
            evidence = result["image_evidence"]["legacy"]
            self.assertTrue(evidence["exists"])
            self.assertEqual(evidence["sha256"], hashlib.sha256(image.read_bytes()).hexdigest())
            self.assertEqual(evidence["png_info"]["png_text"]["Source"], "NovelAI V4.5")

    def test_build_acceptance_record_fails_on_unapproved_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            legacy.write_text(json.dumps({"parameters": _sample_parameters()}), encoding="utf-8")
            changed = _sample_parameters()
            changed["steps"] = 30
            core.write_text(json.dumps({"parameters": changed}), encoding="utf-8")

            record = build_acceptance_record(
                case_id="changed_steps",
                legacy_source=legacy,
                core_source=core,
            )

            self.assertEqual(record["result"], "fail")
            self.assertFalse(record["diff"]["normalized_equal"])
            self.assertEqual(record["diff"]["unapproved_diff_count"], 1)
            self.assertEqual(record["diff"]["unapproved_diffs"][0]["path"], "$.parameters.steps")

    def test_build_acceptance_record_allows_whitelisted_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            legacy.write_text(json.dumps({"parameters": _sample_parameters()}), encoding="utf-8")
            changed = _sample_parameters()
            changed["sampler"] = "ddim_v3"
            core.write_text(json.dumps({"parameters": changed}), encoding="utf-8")

            record = build_acceptance_record(
                case_id="sampler_alias",
                legacy_source=legacy,
                core_source=core,
                whitelist=[{"path": "$.parameters.sampler", "reason": "sampler alias"}],
            )

            self.assertEqual(record["result"], "pass")
            self.assertFalse(record["diff"]["normalized_equal"])
            self.assertEqual(record["diff"]["approved_diff_count"], 1)
            self.assertEqual(record["diff"]["unapproved_diff_count"], 0)

    def test_build_acceptance_record_allows_intentional_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            legacy.write_text(json.dumps({"parameters": _sample_parameters()}), encoding="utf-8")
            changed = _sample_parameters()
            changed["scale"] = 6.0
            core.write_text(json.dumps({"parameters": changed}), encoding="utf-8")

            record = build_acceptance_record(
                case_id="intentional_scale_change",
                legacy_source=legacy,
                core_source=core,
                intentional_differences=[
                    {
                        "path": "$.parameters.scale",
                        "reason": "core intentionally changes this sample",
                    }
                ],
            )

            self.assertEqual(record["result"], "pass")
            self.assertFalse(record["diff"]["normalized_equal"])
            self.assertEqual(record["diff"]["approved_diff_count"], 1)
            self.assertEqual(record["diff"]["whitelisted_diff_count"], 0)
            self.assertEqual(record["diff"]["intentional_diff_count"], 1)
            self.assertEqual(record["diff"]["unapproved_diff_count"], 0)
            self.assertEqual(
                record["intentional_differences"],
                [
                    {
                        "path": "$.parameters.scale",
                        "reason": "core intentionally changes this sample",
                    }
                ],
            )

    def test_verify_acceptance_record_recomputes_intentional_differences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            record_path = root / "acceptance.json"
            legacy.write_text(json.dumps({"parameters": _sample_parameters()}), encoding="utf-8")
            changed = _sample_parameters()
            changed["steps"] = 30
            core.write_text(json.dumps({"parameters": changed}), encoding="utf-8")
            record = build_acceptance_record(
                case_id="intentional_steps",
                legacy_source=legacy,
                core_source=core,
                intentional_differences=[
                    {
                        "path": "$.parameters.steps",
                        "reason": "documented core-side behavior change",
                    }
                ],
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            result = verify_acceptance_record(record_path)

            self.assertTrue(result["match"])
            self.assertEqual(result["result"], "pass")
            self.assertEqual(result["oracle_kind"], "legacy_oracle")
            self.assertEqual(result["diff"]["intentional_diff_count"], 1)
            self.assertEqual(result["diff"]["unapproved_diff_count"], 0)
            self.assertEqual(
                result["intentional_differences"],
                [
                    {
                        "path": "$.parameters.steps",
                        "reason": "documented core-side behavior change",
                    }
                ],
            )

    def test_build_acceptance_record_marks_fixture_oracle_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            record_path = root / "acceptance.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            record = build_acceptance_record(
                case_id="fixture_roundtrip",
                legacy_source=legacy,
                core_source=core,
                oracle_kind="fixture",
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            result = verify_acceptance_record(record_path)

            self.assertEqual(record["oracle_kind"], "fixture")
            self.assertEqual(result["oracle_kind"], "fixture")
            self.assertTrue(result["match"])
            self.assertEqual(result["diff"]["intentional_diff_count"], 0)
            self.assertEqual(result["diff"]["unapproved_diff_count"], 0)

    def test_verify_acceptance_record_recomputes_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            record_path = root / "acceptance.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            record = build_acceptance_record(
                case_id="roundtrip",
                legacy_source=legacy,
                core_source=core,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            result = verify_acceptance_record(record_path)

            self.assertTrue(result["match"])
            self.assertEqual(result["result"], "pass")

    def test_verify_acceptance_record_resolves_relative_paths_from_record_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_dir = root / "acceptance"
            record_dir.mkdir()
            legacy = record_dir / "legacy.json"
            core = record_dir / "core.json"
            record_path = record_dir / "relative_record.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            record_path.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.acceptance-record/v1",
                        "case_id": "relative_paths",
                        "legacy": {"source_path": "legacy.json"},
                        "core": {"source_path": "core.json"},
                        "diff": {"whitelist": []},
                    }
                ),
                encoding="utf-8",
            )

            result = verify_acceptance_record(record_path)

            self.assertTrue(result["match"])
            self.assertEqual(result["case_id"], "relative_paths")

    def test_verify_acceptance_suite_accepts_manifest_and_required_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {"parameters": _sample_parameters()}
            for case_id in ("default_action_001", "foot_detail_001"):
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                record_path = root / f"{case_id}.json"
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                record = build_acceptance_record(
                    case_id=case_id,
                    legacy_source=legacy,
                    core_source=core,
                )
                record_path.write_text(json.dumps(record), encoding="utf-8")
            manifest = root / "suite.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.acceptance-suite/v1",
                        "required_cases": ["default_action", "foot_detail"],
                        "records": [
                            "default_action_001.json",
                            {"path": "foot_detail_001.json"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = verify_acceptance_suite(manifest)

            self.assertTrue(result["match"])
            self.assertEqual(result["record_count"], 2)
            self.assertEqual(result["missing_required_cases"], [])
            self.assertEqual(result["oracle_kind_counts"], {"legacy_oracle": 2})

    def test_verify_acceptance_suite_can_require_legacy_oracle_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "fixture_legacy.json"
            core = root / "fixture_core.json"
            record_path = root / "fixture_record.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            record = build_acceptance_record(
                case_id="fixture_record",
                legacy_source=legacy,
                core_source=core,
                oracle_kind="fixture",
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            fixture_only = verify_acceptance_suite(root)
            required = verify_acceptance_suite(root, require_legacy_oracle=True)

            self.assertTrue(fixture_only["match"])
            self.assertEqual(fixture_only["oracle_kind_counts"], {"fixture": 1})
            self.assertFalse(required["match"])
            self.assertEqual(required["result"], "fail")
            self.assertIn("No legacy_oracle acceptance records found", required["errors"])

            fixture_evidence = verify_acceptance_suite(root, require_legacy_evidence=True)
            self.assertFalse(fixture_evidence["match"])
            self.assertEqual(fixture_evidence["result"], "fail")
            self.assertIn(
                "No legacy_oracle acceptance records found",
                fixture_evidence["errors"],
            )
            self.assertEqual(fixture_evidence["legacy_oracle_evidence_checks"], [])

    def test_verify_acceptance_suite_can_require_legacy_oracle_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            record_path = root / "acceptance.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            record = build_acceptance_record(
                case_id="legacy_without_evidence",
                legacy_source=legacy,
                core_source=core,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            default = verify_acceptance_suite(root)
            strict = verify_acceptance_suite(root, require_legacy_evidence=True)

            self.assertTrue(default["match"])
            self.assertFalse(strict["match"])
            self.assertEqual(strict["legacy_oracle_evidence_fail_count"], 1)
            self.assertIn("Legacy oracle evidence incomplete", strict["errors"])
            evidence_check = strict["legacy_oracle_evidence_checks"][0]
            self.assertEqual(evidence_check["case_id"], "legacy_without_evidence")
            self.assertIn("missing legacy image evidence", evidence_check["messages"])
            self.assertIn("missing core image evidence", evidence_check["messages"])
            self.assertIn("missing GenerationResult evidence", evidence_check["messages"])
            self.assertIn("missing PromptBundle contract evidence", evidence_check["messages"])

    def test_verify_acceptance_suite_requires_png_parameters_for_legacy_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            legacy_image = root / "legacy.png"
            core_image = root / "core.png"
            prompt_bundle = root / "prompt_bundle.json"
            generation_result = root / "generation_result.json"
            record_path = root / "acceptance.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            _write_png_with_text(legacy_image, {"Software": "no parameters"})
            _write_png_with_text(core_image, {"Software": "no parameters"})
            prompt_bundle.write_text(
                json.dumps(_prompt_bundle_fixture()),
                encoding="utf-8",
            )
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [{"path": str(core_image), "filename": "core.png"}],
                        "request_body": payload,
                        "png_info": {"images": [{"path": str(core_image)}]},
                    }
                ),
                encoding="utf-8",
            )
            record = build_acceptance_record(
                case_id="legacy_without_png_parameters",
                legacy_source=legacy,
                core_source=core,
                legacy_image=legacy_image,
                core_image=core_image,
                prompt_bundle=prompt_bundle,
                generation_result=generation_result,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            default = verify_acceptance_suite(root)
            strict = verify_acceptance_suite(root, require_legacy_evidence=True)

            self.assertTrue(default["match"])
            self.assertFalse(strict["match"])
            messages = strict["legacy_oracle_evidence_checks"][0]["messages"]
            self.assertIn("legacy image missing PNG parameters", messages)
            self.assertIn("core image missing PNG parameters", messages)

    def test_verify_acceptance_suite_requires_generation_png_info_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            legacy_image = root / "legacy.png"
            core_image = root / "core.png"
            prompt_bundle = root / "prompt_bundle.json"
            generation_result = root / "generation_result.json"
            record_path = root / "acceptance.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            _write_png_with_text(legacy_image, {"Comment": json.dumps(_sample_parameters())})
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            prompt_bundle.write_text(
                json.dumps(_prompt_bundle_fixture()),
                encoding="utf-8",
            )
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [{"path": str(core_image), "filename": "core.png"}],
                        "request_body": payload,
                        "png_info": {"images": [{"path": str(core_image)}]},
                    }
                ),
                encoding="utf-8",
            )
            record = build_acceptance_record(
                case_id="legacy_without_generation_png_info_content",
                legacy_source=legacy,
                core_source=core,
                legacy_image=legacy_image,
                core_image=core_image,
                prompt_bundle=prompt_bundle,
                generation_result=generation_result,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            default = verify_acceptance_suite(root)
            strict = verify_acceptance_suite(root, require_legacy_evidence=True)

            self.assertTrue(default["match"])
            self.assertFalse(strict["match"])
            messages = strict["legacy_oracle_evidence_checks"][0]["messages"]
            self.assertIn(
                "GenerationResult png_info image[0] missing parameters or error",
                messages,
            )

    def test_verify_acceptance_suite_reports_prompt_bundle_contract_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            legacy_image = root / "legacy.png"
            core_image = root / "core.png"
            prompt_bundle = root / "prompt_bundle.json"
            generation_result = root / "generation_result.json"
            record_path = root / "acceptance.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            _write_png_with_text(legacy_image, {"Comment": json.dumps(_sample_parameters())})
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            prompt_bundle.write_text(
                json.dumps(
                    {
                        "backend": "novelai",
                        "meta": {
                            "shot": {"body_scope": "foot_detail"},
                            "composition": {"character_scope": "foot_detail"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [{"path": str(core_image), "filename": "core.png"}],
                        "request_body": payload,
                        "png_info": {
                            "images": [
                                {
                                    "path": str(core_image),
                                    "parameters": _sample_parameters(),
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            record = build_acceptance_record(
                case_id="legacy_bad_prompt_bundle",
                legacy_source=legacy,
                core_source=core,
                legacy_image=legacy_image,
                core_image=core_image,
                prompt_bundle=prompt_bundle,
                generation_result=generation_result,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            strict = verify_acceptance_suite(root, require_legacy_evidence=True)

            self.assertFalse(strict["match"])
            messages = strict["legacy_oracle_evidence_checks"][0]["messages"]
            self.assertIn("PromptBundle contract evidence failed", messages)
            self.assertIn(
                "PromptBundle contract error: $.schema must be tags-machine-core.prompt-bundle/v1",
                messages,
            )
            self.assertIn("PromptBundle forbidden meta field: $.meta.shot", messages)
            self.assertIn("PromptBundle forbidden backend field: $.backend", messages)

    def test_verify_acceptance_suite_reports_generation_request_diff_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            legacy_image = root / "legacy.png"
            core_image = root / "core.png"
            prompt_bundle = root / "prompt_bundle.json"
            generation_result = root / "generation_result.json"
            record_path = root / "acceptance.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            changed = {
                **payload,
                "parameters": {**_sample_parameters(), "steps": 30},
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            _write_png_with_text(legacy_image, {"Comment": json.dumps(_sample_parameters())})
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            prompt_bundle.write_text(json.dumps(_prompt_bundle_fixture()), encoding="utf-8")
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [{"path": str(core_image), "filename": "core.png"}],
                        "request_body": changed,
                        "png_info": {
                            "images": [
                                {
                                    "path": str(core_image),
                                    "parameters": _sample_parameters(),
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            record = build_acceptance_record(
                case_id="legacy_bad_generation_request",
                legacy_source=legacy,
                core_source=core,
                legacy_image=legacy_image,
                core_image=core_image,
                prompt_bundle=prompt_bundle,
                generation_result=generation_result,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            strict = verify_acceptance_suite(root, require_legacy_evidence=True)

            self.assertFalse(strict["match"])
            messages = strict["legacy_oracle_evidence_checks"][0]["messages"]
            self.assertIn("GenerationResult evidence failed", messages)
            self.assertIn(
                "GenerationResult request_body differs from core source",
                messages,
            )
            self.assertIn("GenerationResult request_body diff at $.parameters.steps", messages)

    def test_verify_acceptance_suite_reports_missing_minimum_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "default_action_001_legacy.json"
            core = root / "default_action_001_core.json"
            record_path = root / "default_action_001.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            record = build_acceptance_record(
                case_id="default_action_001",
                legacy_source=legacy,
                core_source=core,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            result = verify_acceptance_suite(root, require_minimum_set=True)

            self.assertFalse(result["match"])
            self.assertEqual(result["result"], "fail")
            self.assertIn("foot_detail", result["missing_required_cases"])
            self.assertIn("reference_style", result["missing_required_cases"])

    def test_verify_acceptance_suite_checks_minimum_case_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write_record(case_id: str, composition: dict | None = None) -> None:
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                bundle = root / f"{case_id}_bundle.json"
                record_path = root / f"{case_id}.json"
                payload = {"parameters": _minimum_case_parameters(case_id)}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps(_prompt_bundle_fixture(composition)),
                        encoding="utf-8",
                    )
                    prompt_bundle = bundle
                record = build_acceptance_record(
                    case_id=case_id,
                    legacy_source=legacy,
                    core_source=core,
                    prompt_bundle=prompt_bundle,
                )
                record_path.write_text(json.dumps(record), encoding="utf-8")

            write_record("default_action_001")
            write_record(
                "foot_detail_001",
                {
                    "character_scope": "foot_detail",
                    "included_character_sections": ["character", "feet"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes"],
                },
            )
            write_record(
                "hand_detail_001",
                {
                    "character_scope": "hand_detail",
                    "included_character_sections": ["character", "hands"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes", "feet"],
                },
            )
            write_record(
                "complex_character_001",
                {
                    "character_scope": "default",
                    "included_character_sections": ["character", "hair", "eyes", "upper_clothes"],
                    "suppressed_character_sections": [],
                },
            )
            write_record("reference_style_001")

            result = verify_acceptance_suite(root, require_minimum_set=True)

            self.assertTrue(result["match"])
            self.assertEqual(result["case_check_fail_count"], 0)
            self.assertEqual(result["missing_required_cases"], [])
            self.assertEqual(
                {check["required_case"] for check in result["case_checks"]},
                {
                    "default_action",
                    "foot_detail",
                    "hand_detail",
                    "complex_character",
                    "reference_style",
                },
            )

    def test_examples_acceptance_minimum_suite_replays(self):
        result = verify_acceptance_suite(
            PROJECT_ROOT / "examples" / "acceptance" / "suite.yaml",
            require_minimum_set=True,
        )

        self.assertTrue(result["match"])
        self.assertEqual(result["record_count"], 5)
        self.assertEqual(result["case_check_fail_count"], 0)
        self.assertEqual(result["missing_required_cases"], [])
        self.assertEqual(result["oracle_kind_counts"], {"fixture": 5})
        self.assertEqual(
            {check["required_case"] for check in result["case_checks"]},
            {
                "default_action",
                "foot_detail",
                "hand_detail",
                "complex_character",
                "reference_style",
            },
        )
        for record in result["records"]:
            self.assertEqual(record["oracle_kind"], "fixture")
            self.assertTrue(record["diff"]["normalized_equal"])
            self.assertEqual(record["generation_result_evidence"]["result"], "pass")
            self.assertEqual(record["prompt_bundle_contract_evidence"]["result"], "pass")
            self.assertEqual(record["generation_result_evidence"]["image_count"], 1)
            self.assertTrue(record["image_evidence"]["legacy"]["exists"])
            self.assertTrue(record["image_evidence"]["core"]["exists"])

        legacy_required = verify_acceptance_suite(
            PROJECT_ROOT / "examples" / "acceptance" / "suite.yaml",
            require_minimum_set=True,
            require_legacy_oracle=True,
        )
        self.assertFalse(legacy_required["match"])
        self.assertIn("No legacy_oracle acceptance records found", legacy_required["errors"])

    def test_verify_acceptance_suite_requires_minimum_cases_from_legacy_oracles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write_record(
                case_id: str,
                *,
                composition: dict | None = None,
                oracle_kind: str = "fixture",
            ) -> None:
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                bundle = root / f"{case_id}_bundle.json"
                record_path = root / f"{case_id}.json"
                payload = {"parameters": _minimum_case_parameters(case_id)}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps(_prompt_bundle_fixture(composition)),
                        encoding="utf-8",
                    )
                    prompt_bundle = bundle
                record = build_acceptance_record(
                    case_id=case_id,
                    legacy_source=legacy,
                    core_source=core,
                    prompt_bundle=prompt_bundle,
                    oracle_kind=oracle_kind,
                )
                record_path.write_text(json.dumps(record), encoding="utf-8")

            write_record("default_action_001")
            write_record(
                "foot_detail_001",
                composition={
                    "character_scope": "foot_detail",
                    "included_character_sections": ["character", "feet"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes"],
                },
            )
            write_record(
                "hand_detail_001",
                composition={
                    "character_scope": "hand_detail",
                    "included_character_sections": ["character", "hands"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes", "feet"],
                },
            )
            write_record(
                "complex_character_001",
                composition={
                    "character_scope": "default",
                    "included_character_sections": ["character", "hair", "eyes", "upper_clothes"],
                    "suppressed_character_sections": [],
                },
            )
            write_record("reference_style_001")
            write_record("unrelated_legacy_001", oracle_kind="legacy_oracle")

            result = verify_acceptance_suite(
                root,
                require_minimum_set=True,
                require_legacy_oracle=True,
            )

            self.assertFalse(result["match"])
            self.assertEqual(result["missing_required_cases"], [])
            self.assertEqual(result["case_check_fail_count"], 0)
            self.assertEqual(result["oracle_kind_counts"], {"fixture": 5, "legacy_oracle": 1})
            self.assertEqual(
                result["legacy_missing_required_cases"],
                [
                    "default_action",
                    "foot_detail",
                    "hand_detail",
                    "complex_character",
                    "reference_style",
                ],
            )
            self.assertIn(
                "Missing legacy_oracle required cases: default_action, foot_detail, "
                "hand_detail, complex_character, reference_style",
                result["errors"],
            )

    def test_verify_acceptance_suite_fails_bad_minimum_case_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write_record(case_id: str, composition: dict | None = None) -> None:
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                bundle = root / f"{case_id}_bundle.json"
                record_path = root / f"{case_id}.json"
                payload = {"parameters": _minimum_case_parameters(case_id)}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps(_prompt_bundle_fixture(composition)),
                        encoding="utf-8",
                    )
                    prompt_bundle = bundle
                record = build_acceptance_record(
                    case_id=case_id,
                    legacy_source=legacy,
                    core_source=core,
                    prompt_bundle=prompt_bundle,
                )
                record_path.write_text(json.dumps(record), encoding="utf-8")

            write_record("default_action_001")
            write_record(
                "foot_detail_001",
                {
                    "character_scope": "foot_detail",
                    "included_character_sections": ["character", "feet"],
                    "suppressed_character_sections": ["eyes"],
                },
            )
            write_record(
                "hand_detail_001",
                {
                    "character_scope": "hand_detail",
                    "included_character_sections": ["character", "hands"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes", "feet"],
                },
            )
            write_record(
                "complex_character_001",
                {
                    "character_scope": "default",
                    "included_character_sections": ["character", "hair", "eyes", "upper_clothes"],
                    "suppressed_character_sections": [],
                },
            )
            write_record("reference_style_001")

            result = verify_acceptance_suite(root, require_minimum_set=True)

            self.assertFalse(result["match"])
            self.assertEqual(result["missing_required_cases"], [])
            self.assertEqual(result["case_check_fail_count"], 1)
            foot_check = [
                check for check in result["case_checks"] if check["required_case"] == "foot_detail"
            ][0]
            self.assertEqual(foot_check["result"], "fail")
            self.assertIn("upper_clothes", foot_check["messages"][0])

    def test_verify_acceptance_suite_fails_suppressed_prompt_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write_record(
                case_id: str,
                *,
                composition: dict | None = None,
                parameters: dict | None = None,
            ) -> None:
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                bundle = root / f"{case_id}_bundle.json"
                record_path = root / f"{case_id}.json"
                payload = {"parameters": parameters or _minimum_case_parameters(case_id)}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps(_prompt_bundle_fixture(composition)),
                        encoding="utf-8",
                    )
                    prompt_bundle = bundle
                record = build_acceptance_record(
                    case_id=case_id,
                    legacy_source=legacy,
                    core_source=core,
                    prompt_bundle=prompt_bundle,
                )
                record_path.write_text(json.dumps(record), encoding="utf-8")

            bad_foot_params = _minimum_case_parameters("foot_detail_001")
            bad_foot_params["prompt"] = (
                "akemi homura, bare soles, foot focus, purple eyes, school uniform"
            )
            bad_foot_params["v4_prompt"]["caption"]["base_caption"] = bad_foot_params["prompt"]
            write_record("default_action_001")
            write_record(
                "foot_detail_001",
                composition={
                    "character_scope": "foot_detail",
                    "included_character_sections": ["character", "feet"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes"],
                },
                parameters=bad_foot_params,
            )
            write_record(
                "hand_detail_001",
                composition={
                    "character_scope": "hand_detail",
                    "included_character_sections": ["character", "hands"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes", "feet"],
                },
            )
            write_record(
                "complex_character_001",
                composition={
                    "character_scope": "default",
                    "included_character_sections": ["character", "hair", "eyes", "upper_clothes"],
                    "suppressed_character_sections": [],
                },
            )
            write_record("reference_style_001")

            result = verify_acceptance_suite(root, require_minimum_set=True)

            self.assertFalse(result["match"])
            self.assertEqual(result["case_check_fail_count"], 1)
            foot_check = [
                check for check in result["case_checks"] if check["required_case"] == "foot_detail"
            ][0]
            self.assertEqual(foot_check["result"], "fail")
            self.assertIn("prompt contains suppressed section terms", foot_check["messages"][0])
            self.assertIn("school uniform", foot_check["messages"][0])

    def test_verify_acceptance_suite_fails_reference_style_array_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write_record(
                case_id: str,
                *,
                composition: dict | None = None,
                parameters: dict | None = None,
            ) -> None:
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                bundle = root / f"{case_id}_bundle.json"
                record_path = root / f"{case_id}.json"
                payload = {"parameters": parameters or _minimum_case_parameters(case_id)}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps(_prompt_bundle_fixture(composition)),
                        encoding="utf-8",
                    )
                    prompt_bundle = bundle
                record = build_acceptance_record(
                    case_id=case_id,
                    legacy_source=legacy,
                    core_source=core,
                    prompt_bundle=prompt_bundle,
                )
                record_path.write_text(json.dumps(record), encoding="utf-8")

            write_record("default_action_001")
            write_record(
                "foot_detail_001",
                composition={
                    "character_scope": "foot_detail",
                    "included_character_sections": ["character", "feet"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes"],
                },
            )
            write_record(
                "hand_detail_001",
                composition={
                    "character_scope": "hand_detail",
                    "included_character_sections": ["character", "hands"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes", "feet"],
                },
            )
            write_record(
                "complex_character_001",
                composition={
                    "character_scope": "default",
                    "included_character_sections": ["character", "hair", "eyes", "upper_clothes"],
                    "suppressed_character_sections": [],
                },
            )
            bad_reference_params = _sample_parameters(reference="first-reference")
            bad_reference_params["reference_image_multiple"] = [
                "first-reference",
                "second-reference",
            ]
            bad_reference_params["reference_strength_multiple"] = [0.2]
            bad_reference_params["reference_information_extracted_multiple"] = [1.0, 1.0]
            write_record("reference_style_001", parameters=bad_reference_params)

            result = verify_acceptance_suite(root, require_minimum_set=True)

            self.assertFalse(result["match"])
            self.assertEqual(result["missing_required_cases"], [])
            self.assertEqual(result["case_check_fail_count"], 1)
            reference_check = [
                check for check in result["case_checks"] if check["required_case"] == "reference_style"
            ][0]
            self.assertEqual(reference_check["result"], "fail")
            self.assertIn(
                "reference_strength_multiple length mismatch",
                reference_check["messages"][0],
            )

    def test_verify_acceptance_suite_fails_reference_style_missing_director_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write_record(
                case_id: str,
                *,
                composition: dict | None = None,
                parameters: dict | None = None,
            ) -> None:
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                bundle = root / f"{case_id}_bundle.json"
                record_path = root / f"{case_id}.json"
                payload = {"parameters": parameters or _minimum_case_parameters(case_id)}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps(_prompt_bundle_fixture(composition)),
                        encoding="utf-8",
                    )
                    prompt_bundle = bundle
                record = build_acceptance_record(
                    case_id=case_id,
                    legacy_source=legacy,
                    core_source=core,
                    prompt_bundle=prompt_bundle,
                )
                record_path.write_text(json.dumps(record), encoding="utf-8")

            write_record("default_action_001")
            write_record(
                "foot_detail_001",
                composition={
                    "character_scope": "foot_detail",
                    "included_character_sections": ["character", "feet"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes"],
                },
            )
            write_record(
                "hand_detail_001",
                composition={
                    "character_scope": "hand_detail",
                    "included_character_sections": ["character", "hands"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes", "feet"],
                },
            )
            write_record(
                "complex_character_001",
                composition={
                    "character_scope": "default",
                    "included_character_sections": ["character", "hair", "eyes", "upper_clothes"],
                    "suppressed_character_sections": [],
                },
            )
            missing_director_params = _sample_parameters(reference="first-reference")
            missing_director_params["director_reference_images"] = []
            write_record("reference_style_001", parameters=missing_director_params)

            result = verify_acceptance_suite(root, require_minimum_set=True)

            self.assertFalse(result["match"])
            self.assertEqual(result["missing_required_cases"], [])
            self.assertEqual(result["case_check_fail_count"], 1)
            reference_check = [
                check for check in result["case_checks"] if check["required_case"] == "reference_style"
            ][0]
            self.assertEqual(reference_check["result"], "fail")
            self.assertIn("missing director_reference_images", reference_check["messages"][0])

    def test_verify_acceptance_suite_fails_default_action_missing_core_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write_record(
                case_id: str,
                *,
                composition: dict | None = None,
                parameters: dict | None = None,
            ) -> None:
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                bundle = root / f"{case_id}_bundle.json"
                record_path = root / f"{case_id}.json"
                payload = {"parameters": parameters or _minimum_case_parameters(case_id)}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps(_prompt_bundle_fixture(composition)),
                        encoding="utf-8",
                    )
                    prompt_bundle = bundle
                record = build_acceptance_record(
                    case_id=case_id,
                    legacy_source=legacy,
                    core_source=core,
                    prompt_bundle=prompt_bundle,
                )
                record_path.write_text(json.dumps(record), encoding="utf-8")

            bad_default_params = _sample_parameters()
            del bad_default_params["v4_prompt"]
            del bad_default_params["v4_negative_prompt"]
            del bad_default_params["noise_schedule"]
            write_record("default_action_001", parameters=bad_default_params)
            write_record(
                "foot_detail_001",
                composition={
                    "character_scope": "foot_detail",
                    "included_character_sections": ["character", "feet"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes"],
                },
            )
            write_record(
                "hand_detail_001",
                composition={
                    "character_scope": "hand_detail",
                    "included_character_sections": ["character", "hands"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes", "feet"],
                },
            )
            write_record(
                "complex_character_001",
                composition={
                    "character_scope": "default",
                    "included_character_sections": ["character", "hair", "eyes", "upper_clothes"],
                    "suppressed_character_sections": [],
                },
            )
            write_record("reference_style_001")

            result = verify_acceptance_suite(root, require_minimum_set=True)

            self.assertFalse(result["match"])
            self.assertEqual(result["missing_required_cases"], [])
            self.assertEqual(result["case_check_fail_count"], 1)
            default_check = [
                check for check in result["case_checks"] if check["required_case"] == "default_action"
            ][0]
            self.assertEqual(default_check["result"], "fail")
            self.assertIn("noise_schedule", default_check["messages"][0])
            self.assertIn("v4_prompt", default_check["messages"][0])
            self.assertIn("v4_negative_prompt", default_check["messages"][0])

    def test_verify_acceptance_suite_fails_default_action_reference_arrays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write_record(
                case_id: str,
                *,
                composition: dict | None = None,
                parameters: dict | None = None,
            ) -> None:
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                bundle = root / f"{case_id}_bundle.json"
                record_path = root / f"{case_id}.json"
                payload = {"parameters": parameters or _minimum_case_parameters(case_id)}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps(_prompt_bundle_fixture(composition)),
                        encoding="utf-8",
                    )
                    prompt_bundle = bundle
                record = build_acceptance_record(
                    case_id=case_id,
                    legacy_source=legacy,
                    core_source=core,
                    prompt_bundle=prompt_bundle,
                )
                record_path.write_text(json.dumps(record), encoding="utf-8")

            bad_default_params = _minimum_case_parameters("default_action_001")
            bad_default_params["reference_image_multiple"] = ["unexpected-reference"]
            bad_default_params["reference_strength_multiple"] = [0.2]
            del bad_default_params["reference_information_extracted_multiple"]
            bad_default_params["director_reference_images"] = ["unexpected-director"]
            write_record("default_action_001", parameters=bad_default_params)
            write_record(
                "foot_detail_001",
                composition={
                    "character_scope": "foot_detail",
                    "included_character_sections": ["character", "feet"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes"],
                },
            )
            write_record(
                "hand_detail_001",
                composition={
                    "character_scope": "hand_detail",
                    "included_character_sections": ["character", "hands"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes", "feet"],
                },
            )
            write_record(
                "complex_character_001",
                composition={
                    "character_scope": "default",
                    "included_character_sections": ["character", "hair", "eyes", "upper_clothes"],
                    "suppressed_character_sections": [],
                },
            )
            write_record("reference_style_001")

            result = verify_acceptance_suite(root, require_minimum_set=True)

            self.assertFalse(result["match"])
            self.assertEqual(result["missing_required_cases"], [])
            self.assertEqual(result["case_check_fail_count"], 1)
            default_check = [
                check for check in result["case_checks"] if check["required_case"] == "default_action"
            ][0]
            self.assertEqual(default_check["result"], "fail")
            self.assertIn("reference_information_extracted_multiple", default_check["messages"][0])
            self.assertIn(
                "reference_image_multiple must be empty for default_action",
                default_check["messages"][0],
            )
            self.assertIn(
                "reference_strength_multiple must be empty for default_action",
                default_check["messages"][0],
            )
            self.assertIn(
                "director_reference_images must be empty for default_action",
                default_check["messages"][0],
            )

    def test_verify_acceptance_suite_fails_complex_character_scope_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write_record(
                case_id: str,
                *,
                composition: dict | None = None,
                parameters: dict | None = None,
            ) -> None:
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                bundle = root / f"{case_id}_bundle.json"
                record_path = root / f"{case_id}.json"
                payload = {"parameters": parameters or _minimum_case_parameters(case_id)}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps(_prompt_bundle_fixture(composition)),
                        encoding="utf-8",
                    )
                    prompt_bundle = bundle
                record = build_acceptance_record(
                    case_id=case_id,
                    legacy_source=legacy,
                    core_source=core,
                    prompt_bundle=prompt_bundle,
                )
                record_path.write_text(json.dumps(record), encoding="utf-8")

            write_record("default_action_001")
            write_record(
                "foot_detail_001",
                composition={
                    "character_scope": "foot_detail",
                    "included_character_sections": ["character", "feet"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes"],
                },
            )
            write_record(
                "hand_detail_001",
                composition={
                    "character_scope": "hand_detail",
                    "included_character_sections": ["character", "hands"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes", "feet"],
                },
            )
            write_record(
                "complex_character_001",
                composition={
                    "character_scope": "default",
                    "included_character_sections": ["character", "body"],
                    "suppressed_character_sections": ["hair", "eyes", "upper_clothes"],
                },
            )
            write_record("reference_style_001")

            result = verify_acceptance_suite(root, require_minimum_set=True)

            self.assertFalse(result["match"])
            self.assertEqual(result["missing_required_cases"], [])
            self.assertEqual(result["case_check_fail_count"], 1)
            complex_check = [
                check for check in result["case_checks"] if check["required_case"] == "complex_character"
            ][0]
            self.assertEqual(complex_check["result"], "fail")
            self.assertIn("missing included sections", complex_check["messages"][0])
            self.assertIn("unexpected suppressed sections", complex_check["messages"][0])

    def test_verify_acceptance_suite_fails_when_no_records_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = verify_acceptance_suite(root)

            self.assertFalse(result["match"])
            self.assertEqual(result["result"], "fail")
            self.assertEqual(result["record_count"], 0)
            self.assertEqual(result["errors"], ["No acceptance records found"])

    def test_archive_acceptance_case_creates_replayable_oracle_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            source_dir.mkdir()
            legacy = source_dir / "legacy_request.json"
            core = source_dir / "core_render_request.json"
            legacy_image = source_dir / "legacy.png"
            core_image = source_dir / "core.png"
            prompt_bundle = source_dir / "prompt_bundle.json"
            generation_result = source_dir / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            _write_png_with_text(legacy_image, {"Comment": json.dumps(_sample_parameters())})
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            prompt_bundle.write_text(
                json.dumps(
                    _prompt_bundle_fixture(
                        {
                            "character_scope": "foot_detail",
                            "included_character_sections": ["character", "feet"],
                            "suppressed_character_sections": ["eyes", "upper_clothes"],
                        }
                    )
                ),
                encoding="utf-8",
            )
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [
                            {
                                "path": str(core_image),
                                "filename": "core.png",
                                "meta": {"index": 1},
                            }
                        ],
                        "request_body": payload,
                        "png_info": {
                            "images": [
                                {
                                    "path": str(core_image),
                                    "parameters": _sample_parameters(),
                                }
                            ]
                        },
                        "cache_hit": False,
                    }
                ),
                encoding="utf-8",
            )

            archive = archive_acceptance_case(
                case_id="foot_detail_homura_001",
                output_dir=root / "acceptance",
                legacy_source=legacy,
                core_source=core,
                legacy_image=legacy_image,
                core_image=core_image,
                prompt_bundle=prompt_bundle,
                generation_result=generation_result,
                required_cases=["foot_detail"],
                notes=["oracle package"],
            )
            suite = verify_acceptance_suite(root / "acceptance" / "suite.yaml")

            case_dir = Path(archive["case_dir"])
            record_path = Path(archive["record_path"])
            record = archive["record"]
            self.assertEqual(archive["result"], "pass")
            self.assertTrue(record_path.exists())
            self.assertTrue((case_dir / "legacy" / "source.json").exists())
            self.assertTrue((case_dir / "core" / "render_request.json").exists())
            self.assertEqual(record["legacy"]["source_path"], "legacy/source.json")
            self.assertEqual(record["core"]["render_request_path"], "core/render_request.json")
            self.assertEqual(record["core"]["prompt_bundle_path"], "core/prompt_bundle.json")
            self.assertEqual(
                record["core"]["generation_result_path"],
                "core/generation_result.json",
            )
            self.assertEqual(record["generation_result_evidence"]["result"], "pass")
            self.assertEqual(
                record["generation_result_evidence"]["request_body"]["diff"]["diff_count"],
                0,
            )
            generation_image = record["generation_result_evidence"]["images"][0]
            self.assertEqual(generation_image["path"], "image.png")
            self.assertEqual(generation_image["resolved_path"], "core/image.png")
            self.assertTrue(generation_image["exists"])
            self.assertEqual(generation_image["bytes"], core_image.stat().st_size)
            self.assertEqual(
                generation_image["sha256"],
                hashlib.sha256(core_image.read_bytes()).hexdigest(),
            )
            archived_generation = json.loads(
                (case_dir / "core" / "generation_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(archived_generation["images"][0]["path"], "image.png")
            self.assertEqual(archived_generation["images"][0]["filename"], "image.png")
            self.assertEqual(archived_generation["png_info"]["images"][0]["path"], "image.png")
            self.assertEqual(record["archive"]["artifacts"]["legacy_image"], "legacy/image.png")
            self.assertEqual(record["composition"]["character_scope"], "foot_detail")
            self.assertTrue(suite["match"])
            self.assertEqual(suite["missing_required_cases"], [])
            strict_suite = verify_acceptance_suite(
                root / "acceptance" / "suite.yaml",
                require_legacy_evidence=True,
            )
            self.assertTrue(strict_suite["match"])
            self.assertEqual(strict_suite["legacy_oracle_evidence_fail_count"], 0)
            self.assertEqual(
                strict_suite["legacy_oracle_evidence_checks"][0]["result"],
                "pass",
            )
            shutil.rmtree(source_dir)
            replayed_suite = verify_acceptance_suite(root / "acceptance" / "suite.yaml")
            self.assertTrue(replayed_suite["match"])
            self.assertEqual(replayed_suite["records"][0]["generation_result_evidence"]["result"], "pass")

    def test_archive_acceptance_case_archives_generation_result_images_without_core_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            source_dir.mkdir()
            legacy = source_dir / "legacy_request.json"
            core = source_dir / "core_render_request.json"
            legacy_image = source_dir / "legacy.png"
            core_image = source_dir / "generated.png"
            second_core_image = source_dir / "generated_second.png"
            prompt_bundle = source_dir / "prompt_bundle.json"
            generation_result = source_dir / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            _write_png_with_text(legacy_image, {"Comment": json.dumps(_sample_parameters())})
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            _write_png_with_text(second_core_image, {"Comment": json.dumps(_sample_parameters())})
            prompt_bundle.write_text(json.dumps(_prompt_bundle_fixture()), encoding="utf-8")
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [
                            {"path": str(core_image), "filename": "generated.png"},
                            {
                                "path": str(second_core_image),
                                "filename": "generated_second.png",
                            },
                        ],
                        "request_body": payload,
                        "png_info": {
                            "images": [
                                {
                                    "path": str(core_image),
                                    "parameters": _sample_parameters(),
                                },
                                {
                                    "path": str(second_core_image),
                                    "parameters": _sample_parameters(),
                                },
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            archive = archive_acceptance_case(
                case_id="generation_result_images_only_001",
                output_dir=root / "acceptance",
                legacy_source=legacy,
                core_source=core,
                legacy_image=legacy_image,
                prompt_bundle=prompt_bundle,
                generation_result=generation_result,
            )

            case_dir = Path(archive["case_dir"])
            record = archive["record"]
            self.assertEqual(archive["result"], "pass")
            self.assertTrue((case_dir / "core" / "image.png").exists())
            self.assertTrue((case_dir / "core" / "image_1.png").exists())
            self.assertEqual(record["core"]["image_path"], "core/image.png")
            self.assertEqual(record["archive"]["artifacts"]["core_image"], "core/image.png")
            self.assertEqual(record["generation_result_evidence"]["image_count"], 2)
            self.assertEqual(
                record["generation_result_evidence"]["images"][0]["resolved_path"],
                "core/image.png",
            )
            self.assertEqual(
                record["generation_result_evidence"]["images"][1]["resolved_path"],
                "core/image_1.png",
            )
            archived_generation = json.loads(
                (case_dir / "core" / "generation_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [item["path"] for item in archived_generation["images"]],
                ["image.png", "image_1.png"],
            )
            self.assertEqual(
                [item["filename"] for item in archived_generation["images"]],
                ["image.png", "image_1.png"],
            )
            self.assertEqual(
                [item["path"] for item in archived_generation["png_info"]["images"]],
                ["image.png", "image_1.png"],
            )

            shutil.rmtree(source_dir)
            strict_suite = verify_acceptance_suite(
                root / "acceptance" / "suite.yaml",
                require_legacy_evidence=True,
            )
            self.assertTrue(strict_suite["match"])
            self.assertEqual(strict_suite["legacy_oracle_evidence_fail_count"], 0)

    def test_build_acceptance_record_fails_generation_result_missing_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            generation_result = root / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [
                            {
                                "path": "missing.png",
                                "filename": "missing.png",
                                "meta": {"index": 1},
                            }
                        ],
                        "request_body": payload,
                    }
                ),
                encoding="utf-8",
            )

            record = build_acceptance_record(
                case_id="missing_generation_image",
                legacy_source=legacy,
                core_source=core,
                generation_result=generation_result,
            )

            evidence = record["generation_result_evidence"]
            self.assertEqual(record["result"], "fail")
            self.assertEqual(evidence["result"], "fail")
            self.assertFalse(evidence["images"][0]["exists"])
            self.assertIn("GenerationResult image[0] does not exist", evidence["errors"][0])

    def test_build_acceptance_record_fails_generation_result_contract_shape_errors(self):
        cases = [
            (
                "generation_result_bad_schema",
                {"schema": "bad-generation-result"},
                "$.schema must be tags-machine-core.generation-result/v1",
            ),
            (
                "generation_result_bad_backend",
                {"backend": "unknown"},
                "$.backend must be one of: comfyui, novelai, sd",
            ),
            (
                "generation_result_bad_images",
                {"images": "not a list"},
                "$.images must be a list",
            ),
            (
                "generation_result_bad_cache_hit",
                {"cache_hit": "false"},
                "$.cache_hit must be a boolean",
            ),
            (
                "generation_result_bad_created_at",
                {"created_at": 123},
                "$.created_at must be a string",
            ),
            (
                "generation_result_bad_png_info",
                {"png_info": "not an object"},
                "GenerationResult png_info must be an object",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for case_id, override, expected_error in cases:
                with self.subTest(case_id=case_id):
                    case_dir = root / case_id
                    case_dir.mkdir()
                    legacy = case_dir / "legacy.json"
                    core = case_dir / "core.json"
                    generation_result = case_dir / "generation_result.json"
                    payload = {
                        "input": "akemi homura, foot focus",
                        "model": "nai-diffusion-4-5-full",
                        "action": "generate",
                        "parameters": _sample_parameters(),
                    }
                    legacy.write_text(json.dumps(payload), encoding="utf-8")
                    core.write_text(
                        json.dumps(
                            {
                                "schema": "tags-machine-core.render-request/v1",
                                "backend": "novelai",
                                "prompt": "akemi homura, foot focus",
                                "negative_prompt": "bad feet",
                                "model": "nai-diffusion-4-5-full",
                                "params": _sample_parameters(),
                                "meta": {"action": "generate"},
                            }
                        ),
                        encoding="utf-8",
                    )
                    generation_result.write_text(
                        json.dumps(
                            {
                                "schema": "tags-machine-core.generation-result/v1",
                                "backend": "novelai",
                                "images": [],
                                "request_body": payload,
                                **override,
                            }
                        ),
                        encoding="utf-8",
                    )

                    record = build_acceptance_record(
                        case_id=case_id,
                        legacy_source=legacy,
                        core_source=core,
                        generation_result=generation_result,
                    )

                    evidence = record["generation_result_evidence"]
                    self.assertEqual(record["result"], "fail")
                    self.assertEqual(evidence["result"], "fail")
                    self.assertIn(expected_error, evidence["errors"])
                    self.assertIn(expected_error, evidence["contract_errors"] + evidence["errors"])

    def test_build_acceptance_record_fails_generation_result_backend_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            generation_result = root / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "comfyui",
                        "images": [],
                        "request_body": payload,
                    }
                ),
                encoding="utf-8",
            )

            record = build_acceptance_record(
                case_id="generation_result_backend_mismatch",
                legacy_source=legacy,
                core_source=core,
                generation_result=generation_result,
            )

            evidence = record["generation_result_evidence"]
            self.assertEqual(record["result"], "fail")
            self.assertEqual(evidence["result"], "fail")
            self.assertEqual(evidence["backend_check"]["expected"], "novelai")
            self.assertEqual(evidence["backend_check"]["actual"], "comfyui")
            self.assertIn(
                "GenerationResult backend differs from core RenderRequest backend: "
                "expected novelai, got comfyui",
                evidence["errors"],
            )

    def test_build_acceptance_record_fails_generation_result_image_item_shape_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            core_image = root / "core.png"
            generation_result = root / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [
                            {
                                "path": str(core_image),
                                "filename": "",
                                "meta": "not an object",
                            },
                            {
                                "path": 123,
                                "filename": "bad.png",
                            },
                        ],
                        "request_body": payload,
                        "png_info": {
                            "images": [
                                {
                                    "path": str(core_image),
                                    "parameters": _sample_parameters(),
                                },
                                {
                                    "path": "",
                                    "parameters": _sample_parameters(),
                                },
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            record = build_acceptance_record(
                case_id="generation_result_bad_image_items",
                legacy_source=legacy,
                core_source=core,
                generation_result=generation_result,
            )

            evidence = record["generation_result_evidence"]
            self.assertEqual(record["result"], "fail")
            self.assertEqual(evidence["result"], "fail")
            self.assertIn(
                "GenerationResult image[0].filename must be a non-empty string",
                evidence["errors"],
            )
            self.assertIn(
                "GenerationResult image[0].meta must be an object",
                evidence["errors"],
            )
            self.assertIn(
                "GenerationResult image[1].path must be a non-empty string",
                evidence["errors"],
            )
            self.assertIn(
                "GenerationResult png_info image[1].path must be a non-empty string",
                evidence["errors"],
            )

    def test_build_acceptance_record_fails_generation_result_png_info_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            core_image = root / "core.png"
            other_image = root / "other.png"
            generation_result = root / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            _write_png_with_text(other_image, {"Comment": json.dumps(_sample_parameters())})
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [
                            {
                                "path": str(core_image),
                                "filename": "core.png",
                                "meta": {"index": 1},
                            }
                        ],
                        "request_body": payload,
                        "png_info": {"images": [{"path": str(other_image)}]},
                    }
                ),
                encoding="utf-8",
            )

            record = build_acceptance_record(
                case_id="generation_result_png_info_mismatch",
                legacy_source=legacy,
                core_source=core,
                generation_result=generation_result,
            )

            evidence = record["generation_result_evidence"]
            self.assertEqual(record["result"], "fail")
            self.assertEqual(evidence["result"], "fail")
            self.assertEqual(evidence["png_info"]["image_count"], 1)
            self.assertIn(
                "GenerationResult png_info image[0] path differs from images[0]",
                evidence["errors"],
            )

    def test_build_acceptance_record_fails_generation_result_png_parameters_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            core_image = root / "core.png"
            generation_result = root / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [
                            {
                                "path": str(core_image),
                                "filename": "core.png",
                                "meta": {"index": 1},
                            }
                        ],
                        "request_body": payload,
                        "png_info": {
                            "images": [
                                {
                                    "path": str(core_image),
                                    "parameters": {
                                        **_sample_parameters(),
                                        "steps": 30,
                                    },
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            record = build_acceptance_record(
                case_id="generation_result_png_parameters_mismatch",
                legacy_source=legacy,
                core_source=core,
                generation_result=generation_result,
            )

            evidence = record["generation_result_evidence"]
            self.assertEqual(record["result"], "fail")
            self.assertEqual(evidence["result"], "fail")
            self.assertIn(
                "GenerationResult png_info image[0] parameters differ from image PNG",
                evidence["errors"],
            )
            self.assertEqual(
                evidence["png_info"]["images"][0]["parameter_check"]["result"],
                "fail",
            )
            self.assertEqual(
                evidence["png_info"]["images"][0]["parameter_check"]["diffs"][0]["path"],
                "$.parameters.steps",
            )

    def test_build_acceptance_record_fails_generation_result_png_error_on_readable_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            core_image = root / "core.png"
            generation_result = root / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            _write_png_with_text(core_image, {"Comment": json.dumps(_sample_parameters())})
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [
                            {
                                "path": str(core_image),
                                "filename": "core.png",
                                "meta": {"index": 1},
                            }
                        ],
                        "request_body": payload,
                        "png_info": {
                            "images": [
                                {
                                    "path": str(core_image),
                                    "error": "Not a PNG file",
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            record = build_acceptance_record(
                case_id="generation_result_png_error_on_readable_image",
                legacy_source=legacy,
                core_source=core,
                generation_result=generation_result,
            )

            evidence = record["generation_result_evidence"]
            self.assertEqual(record["result"], "fail")
            self.assertEqual(evidence["result"], "fail")
            self.assertIn(
                "GenerationResult png_info image[0] error contradicts readable PNG",
                evidence["errors"],
            )
            self.assertEqual(
                evidence["png_info"]["images"][0]["error_check"]["result"],
                "fail",
            )

    def test_build_acceptance_record_fails_generation_result_png_info_shape_errors(self):
        cases = [
            (
                "generation_result_png_parameters_not_object",
                {"parameters": "not an object"},
                "GenerationResult png_info image[0] parameters must be an object",
            ),
            (
                "generation_result_png_parameters_and_error",
                {"parameters": _sample_parameters(), "error": "Not a PNG file"},
                "GenerationResult png_info image[0] has both parameters and error",
            ),
            (
                "generation_result_png_empty_error",
                {"error": "   "},
                "GenerationResult png_info image[0] error must be a non-empty string",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for case_id, png_info_extra, expected_error in cases:
                with self.subTest(case_id=case_id):
                    case_dir = root / case_id
                    case_dir.mkdir()
                    legacy = case_dir / "legacy.json"
                    core = case_dir / "core.json"
                    core_image = case_dir / "core.png"
                    generation_result = case_dir / "generation_result.json"
                    payload = {
                        "input": "akemi homura, foot focus",
                        "model": "nai-diffusion-4-5-full",
                        "action": "generate",
                        "parameters": _sample_parameters(),
                    }
                    legacy.write_text(json.dumps(payload), encoding="utf-8")
                    core.write_text(
                        json.dumps(
                            {
                                "schema": "tags-machine-core.render-request/v1",
                                "backend": "novelai",
                                "prompt": "akemi homura, foot focus",
                                "negative_prompt": "bad feet",
                                "model": "nai-diffusion-4-5-full",
                                "params": _sample_parameters(),
                                "meta": {"action": "generate"},
                            }
                        ),
                        encoding="utf-8",
                    )
                    _write_png_with_text(
                        core_image,
                        {"Comment": json.dumps(_sample_parameters())},
                    )
                    generation_result.write_text(
                        json.dumps(
                            {
                                "schema": "tags-machine-core.generation-result/v1",
                                "backend": "novelai",
                                "images": [
                                    {
                                        "path": str(core_image),
                                        "filename": "core.png",
                                        "meta": {"index": 1},
                                    }
                                ],
                                "request_body": payload,
                                "png_info": {
                                    "images": [
                                        {
                                            "path": str(core_image),
                                            **png_info_extra,
                                        }
                                    ]
                                },
                            }
                        ),
                        encoding="utf-8",
                    )

                    record = build_acceptance_record(
                        case_id=case_id,
                        legacy_source=legacy,
                        core_source=core,
                        generation_result=generation_result,
                    )

                    evidence = record["generation_result_evidence"]
                    self.assertEqual(record["result"], "fail")
                    self.assertEqual(evidence["result"], "fail")
                    self.assertIn(expected_error, evidence["errors"])

    def test_build_acceptance_record_fails_generation_result_request_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            generation_result = root / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            changed = {
                **payload,
                "parameters": {**_sample_parameters(), "steps": 30},
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [],
                        "request_body": changed,
                    }
                ),
                encoding="utf-8",
            )

            record = build_acceptance_record(
                case_id="generation_result_mismatch",
                legacy_source=legacy,
                core_source=core,
                generation_result=generation_result,
            )

            self.assertEqual(record["result"], "fail")
            evidence = record["generation_result_evidence"]
            self.assertEqual(evidence["result"], "fail")
            self.assertIn(
                "GenerationResult request_body differs from core source",
                evidence["errors"],
            )
            self.assertEqual(
                evidence["request_body"]["diff"]["diffs"][0]["path"],
                "$.parameters.steps",
            )

    def test_build_acceptance_record_fails_generation_result_missing_director_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            generation_result = root / "generation_result.json"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            changed_params = _sample_parameters()
            del changed_params["director_reference_images"]
            changed = {
                **payload,
                "parameters": changed_params,
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [],
                        "request_body": changed,
                    }
                ),
                encoding="utf-8",
            )

            record = build_acceptance_record(
                case_id="generation_result_missing_director_reference",
                legacy_source=legacy,
                core_source=core,
                generation_result=generation_result,
            )

            self.assertEqual(record["result"], "fail")
            evidence = record["generation_result_evidence"]
            self.assertEqual(evidence["result"], "fail")
            self.assertIn(
                "GenerationResult request_body differs from core source",
                evidence["errors"],
            )
            self.assertEqual(
                evidence["request_body"]["diff"]["diffs"][0]["path"],
                "$.parameters.director_reference_images",
            )

    def test_cli_create_and_verify_acceptance_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            record_path = root / "acceptance.yaml"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                create_exit = main(
                    [
                        "create-acceptance-record",
                        "--case-id",
                        "cli_roundtrip",
                        "--legacy-source",
                        str(legacy),
                        "--core-source",
                        str(core),
                        "--output",
                        str(record_path),
                    ]
                )
            created = json.loads(stdout.getvalue())

            verify_stdout = io.StringIO()
            with redirect_stdout(verify_stdout):
                verify_exit = main(["verify-acceptance-record", str(record_path)])
            verified = json.loads(verify_stdout.getvalue())

            self.assertEqual(create_exit, 0)
            self.assertEqual(verify_exit, 0)
            self.assertEqual(created["result"], "pass")
            self.assertEqual(created["oracle_kind"], "legacy_oracle")
            self.assertTrue(verified["match"])
            self.assertEqual(verified["oracle_kind"], "legacy_oracle")
            self.assertTrue(record_path.exists())

    def test_cli_acceptance_record_fixture_kind_requires_legacy_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            record_path = root / "acceptance.yaml"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                create_exit = main(
                    [
                        "create-acceptance-record",
                        "--case-id",
                        "fixture_cli",
                        "--legacy-source",
                        str(legacy),
                        "--core-source",
                        str(core),
                        "--oracle-kind",
                        "fixture",
                        "--output",
                        str(record_path),
                    ]
                )
            created = json.loads(stdout.getvalue())

            suite_stdout = io.StringIO()
            with redirect_stdout(suite_stdout):
                suite_exit = main(
                    [
                        "verify-acceptance-suite",
                        str(root),
                        "--require-legacy-oracle",
                    ]
                )
            suite = json.loads(suite_stdout.getvalue())

            self.assertEqual(create_exit, 0)
            self.assertEqual(created["oracle_kind"], "fixture")
            self.assertEqual(suite_exit, 2)
            self.assertFalse(suite["match"])
            self.assertEqual(suite["oracle_kind_counts"], {"fixture": 1})
            self.assertIn("No legacy_oracle acceptance records found", suite["errors"])

    def test_cli_verify_acceptance_suite_can_require_legacy_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            record_path = root / "acceptance.yaml"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")

            create_stdout = io.StringIO()
            with redirect_stdout(create_stdout):
                create_exit = main(
                    [
                        "create-acceptance-record",
                        "--case-id",
                        "legacy_without_images",
                        "--legacy-source",
                        str(legacy),
                        "--core-source",
                        str(core),
                        "--output",
                        str(record_path),
                    ]
                )

            suite_stdout = io.StringIO()
            with redirect_stdout(suite_stdout):
                suite_exit = main(
                    [
                        "verify-acceptance-suite",
                        str(root),
                        "--require-legacy-evidence",
                    ]
                )
            suite = json.loads(suite_stdout.getvalue())

            self.assertEqual(create_exit, 0)
            self.assertEqual(suite_exit, 2)
            self.assertEqual(suite["legacy_oracle_evidence_fail_count"], 1)
            self.assertIn("Legacy oracle evidence incomplete", suite["errors"])

    def test_module_cli_exits_nonzero_when_suite_requires_legacy_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            record_path = root / "acceptance.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            record = build_acceptance_record(
                case_id="fixture_module_cli",
                legacy_source=legacy,
                core_source=core,
                oracle_kind="fixture",
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            env = {
                **os.environ,
                "PYTHONPATH": str(PROJECT_ROOT / "src")
                + os.pathsep
                + os.environ.get("PYTHONPATH", ""),
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tags_machine_core",
                    "verify-acceptance-suite",
                    str(root),
                    "--require-legacy-oracle",
                ],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            data = json.loads(result.stdout)
            self.assertFalse(data["match"])
            self.assertIn("No legacy_oracle acceptance records found", data["errors"])

    def test_cli_create_acceptance_record_accepts_generation_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            generation_result = root / "generation_result.json"
            record_path = root / "acceptance.yaml"
            payload = {
                "input": "akemi homura, foot focus",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": _sample_parameters(),
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.render-request/v1",
                        "backend": "novelai",
                        "prompt": "akemi homura, foot focus",
                        "negative_prompt": "bad feet",
                        "model": "nai-diffusion-4-5-full",
                        "params": _sample_parameters(),
                        "meta": {"action": "generate"},
                    }
                ),
                encoding="utf-8",
            )
            generation_result.write_text(
                json.dumps(
                    {
                        "schema": "tags-machine-core.generation-result/v1",
                        "backend": "novelai",
                        "images": [],
                        "request_body": payload,
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                create_exit = main(
                    [
                        "create-acceptance-record",
                        "--case-id",
                        "cli_generation_result",
                        "--legacy-source",
                        str(legacy),
                        "--core-source",
                        str(core),
                        "--generation-result",
                        str(generation_result),
                        "--output",
                        str(record_path),
                    ]
                )
            created = json.loads(stdout.getvalue())

            verify_stdout = io.StringIO()
            with redirect_stdout(verify_stdout):
                verify_exit = main(["verify-acceptance-record", str(record_path)])
            verified = json.loads(verify_stdout.getvalue())

            self.assertEqual(create_exit, 0)
            self.assertEqual(verify_exit, 0)
            self.assertEqual(created["generation_result_evidence"]["result"], "pass")
            self.assertEqual(verified["generation_result_evidence"]["result"], "pass")

    def test_cli_create_acceptance_record_allows_intentional_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            record_path = root / "acceptance.yaml"
            legacy.write_text(json.dumps({"parameters": _sample_parameters()}), encoding="utf-8")
            changed = _sample_parameters()
            changed["scale"] = 6.0
            core.write_text(json.dumps({"parameters": changed}), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                create_exit = main(
                    [
                        "create-acceptance-record",
                        "--case-id",
                        "intentional_cli",
                        "--legacy-source",
                        str(legacy),
                        "--core-source",
                        str(core),
                        "--intentional-difference",
                        "$.parameters.scale=core intentionally changes scale",
                        "--output",
                        str(record_path),
                    ]
                )
            created = json.loads(stdout.getvalue())

            verify_stdout = io.StringIO()
            with redirect_stdout(verify_stdout):
                verify_exit = main(["verify-acceptance-record", str(record_path)])
            verified = json.loads(verify_stdout.getvalue())

            self.assertEqual(create_exit, 0)
            self.assertEqual(verify_exit, 0)
            self.assertEqual(created["result"], "pass")
            self.assertEqual(created["diff"]["intentional_diff_count"], 1)
            self.assertEqual(created["diff"]["unapproved_diff_count"], 0)
            self.assertEqual(
                created["intentional_differences"][0]["reason"],
                "core intentionally changes scale",
            )
            self.assertTrue(verified["match"])
            self.assertEqual(verified["diff"]["intentional_diff_count"], 1)

    def test_cli_create_acceptance_record_returns_nonzero_for_unapproved_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            legacy.write_text(json.dumps({"parameters": _sample_parameters()}), encoding="utf-8")
            changed = _sample_parameters()
            changed["scale"] = 6.0
            core.write_text(json.dumps({"parameters": changed}), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "create-acceptance-record",
                        "--case-id",
                        "scale_changed",
                        "--legacy-source",
                        str(legacy),
                        "--core-source",
                        str(core),
                    ]
                )
            data = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 2)
            self.assertEqual(data["result"], "fail")
            self.assertEqual(data["diff"]["unapproved_diffs"][0]["path"], "$.parameters.scale")

    def test_cli_verify_acceptance_suite_returns_nonzero_for_missing_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "default_action_001_legacy.json"
            core = root / "default_action_001_core.json"
            record_path = root / "default_action_001.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")
            record = build_acceptance_record(
                case_id="default_action_001",
                legacy_source=legacy,
                core_source=core,
            )
            record_path.write_text(json.dumps(record), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "verify-acceptance-suite",
                        str(root),
                        "--required-case",
                        "default_action",
                        "--required-case",
                        "foot_detail",
                    ]
                )
            data = json.loads(stdout.getvalue())

            self.assertEqual(exit_code, 2)
            self.assertFalse(data["match"])
            self.assertEqual(data["missing_required_cases"], ["foot_detail"])

    def test_cli_archive_acceptance_case_updates_suite_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            core = root / "core.json"
            payload = {"parameters": _sample_parameters()}
            legacy.write_text(json.dumps(payload), encoding="utf-8")
            core.write_text(json.dumps(payload), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "archive-acceptance-case",
                        "--case-id",
                        "default_action_001",
                        "--output-dir",
                        str(root / "acceptance"),
                        "--legacy-source",
                        str(legacy),
                        "--core-source",
                        str(core),
                        "--required-case",
                        "default_action",
                    ]
                )
            archive = json.loads(stdout.getvalue())

            verify_stdout = io.StringIO()
            with redirect_stdout(verify_stdout):
                verify_exit = main(
                    ["verify-acceptance-suite", str(root / "acceptance" / "suite.yaml")]
                )
            suite = json.loads(verify_stdout.getvalue())

            self.assertEqual(exit_code, 0)
            self.assertEqual(verify_exit, 0)
            self.assertEqual(archive["result"], "pass")
            self.assertTrue(Path(archive["record_path"]).exists())
            self.assertEqual(suite["record_count"], 1)
            self.assertEqual(suite["missing_required_cases"], [])


if __name__ == "__main__":
    unittest.main()
