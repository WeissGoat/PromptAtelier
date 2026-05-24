import io
import hashlib
import json
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path

from tags_machine_core.cli import main
from tags_machine_core.verification import (
    archive_acceptance_case,
    build_acceptance_record,
    compare_render_parameters,
    normalize_render_parameters,
    read_image_parameters,
    verify_acceptance_record,
    verify_acceptance_suite,
)


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


class VerificationTest(unittest.TestCase):
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
                    {
                        "meta": {
                            "composition": {
                                "character_scope": "foot_detail",
                                "included_character_sections": ["character", "feet"],
                                "suppressed_character_sections": ["eyes", "upper_clothes"],
                            }
                        }
                    }
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
            self.assertEqual(record["notes"], ["sample acceptance"])

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
                payload = {"parameters": _sample_parameters()}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps({"meta": {"composition": composition}}),
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
            write_record("complex_character_001")
            write_record("reference_style_001")

            result = verify_acceptance_suite(root, require_minimum_set=True)

            self.assertTrue(result["match"])
            self.assertEqual(result["case_check_fail_count"], 0)
            self.assertEqual(result["missing_required_cases"], [])
            self.assertEqual(
                {check["required_case"] for check in result["case_checks"]},
                {"foot_detail", "hand_detail", "reference_style"},
            )

    def test_verify_acceptance_suite_fails_bad_minimum_case_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write_record(case_id: str, composition: dict | None = None) -> None:
                legacy = root / f"{case_id}_legacy.json"
                core = root / f"{case_id}_core.json"
                bundle = root / f"{case_id}_bundle.json"
                record_path = root / f"{case_id}.json"
                payload = {"parameters": _sample_parameters()}
                legacy.write_text(json.dumps(payload), encoding="utf-8")
                core.write_text(json.dumps(payload), encoding="utf-8")
                prompt_bundle = None
                if composition is not None:
                    bundle.write_text(
                        json.dumps({"meta": {"composition": composition}}),
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
            write_record("complex_character_001")
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
                    {
                        "meta": {
                            "composition": {
                                "character_scope": "foot_detail",
                                "included_character_sections": ["character", "feet"],
                                "suppressed_character_sections": ["eyes", "upper_clothes"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            generation_result.write_text(
                json.dumps({"schema": "tags-machine-core.generation-result/v1", "images": []}),
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
            self.assertEqual(record["archive"]["artifacts"]["legacy_image"], "legacy/image.png")
            self.assertEqual(record["composition"]["character_scope"], "foot_detail")
            self.assertTrue(suite["match"])
            self.assertEqual(suite["missing_required_cases"], [])

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
            self.assertTrue(verified["match"])
            self.assertTrue(record_path.exists())

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
