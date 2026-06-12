import io
import json
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path

from tags_machine_core.cli import main
from tags_machine_core.verification import build_prompt_policy_acceptance_report


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


def _params(prompt: str) -> dict:
    return {
        "prompt": prompt,
        "negative_prompt": "bad feet",
        "model": "nai-diffusion-4-5-full",
        "seed": 123,
        "width": 1024,
        "height": 1024,
        "sampler": "k_euler",
        "steps": 28,
        "scale": 5.0,
        "reference_image_multiple": [],
        "reference_strength_multiple": [],
        "reference_information_extracted_multiple": [],
        "director_reference_images": [],
    }


def _payload(prompt: str) -> dict:
    parameters = _params(prompt)
    return {
        "input": prompt,
        "model": "nai-diffusion-4-5-full",
        "action": "generate",
        "parameters": parameters,
    }


def _prompt_bundle(prompt: str) -> dict:
    return {
        "schema": "tags-machine-core.prompt-bundle/v2",
        "prompt": {"positive": prompt, "negative": "bad feet"},
        "meta": {
            "composer_type": "script",
            "composer_version": "v1",
            "composition": {
                "character_scope": None,
                "included_character_sections": [],
                "suppressed_character_sections": [],
            },
            "nodes": [],
            "extra": {
                "policy": {
                    "enabled": True,
                    "profile": "balanced",
                    "target": "full_prompt",
                    "enabled_rules": [
                        "tag_normalize@v1",
                        "dedupe@v1",
                        "tag_conflict@v1",
                        "character_count@v1",
                    ],
                    "disabled_rules": [],
                },
                "policy_trace": [
                    {
                        "rule": "tag_conflict",
                        "action": "remove",
                        "token": "high_heels",
                        "reason": "bare feet conflict",
                    }
                ],
            },
        },
        "cache": {"cacheable": True, "cache_key": "sha256:abc", "cache_hit": False},
    }


def _generation_result(core_image: Path, prompt: str) -> dict:
    return {
        "schema": "tags-machine-core.generation-result/v1",
        "backend": "novelai",
        "images": [
            {
                "path": str(core_image),
                "filename": core_image.name,
                "meta": {"index": 1},
            }
        ],
        "request_body": _payload(prompt),
        "png_info": {
            "images": [
                {
                    "path": str(core_image),
                    "parameters": _params(prompt),
                }
            ]
        },
        "cache_hit": False,
    }


class PromptPolicyAcceptanceTest(unittest.TestCase):
    def test_prompt_policy_acceptance_passes_with_real_image_evidence_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_prompt = "1girl, bare feet, high heels"
            core_prompt = "1girl, bare_feet"
            legacy_image = root / "legacy.png"
            core_image = root / "core.png"
            legacy_image.write_bytes(
                _png_bytes_with_text({"Comment": json.dumps(_params(legacy_prompt))})
            )
            core_image.write_bytes(_png_bytes_with_text({"Comment": json.dumps(_params(core_prompt))}))
            run_result = {
                "schema": "tags-machine-core.run-prompt-result/v1",
                "status": "ready",
                "dry_run": False,
                "prompt_bundle": _prompt_bundle(core_prompt),
                "generation_result": _generation_result(core_image, core_prompt),
            }
            run_result_path = root / "core_run_result.json"
            run_result_path.write_text(json.dumps(run_result), encoding="utf-8")

            report = build_prompt_policy_acceptance_report(
                legacy_image=legacy_image,
                core_run_result=run_result_path,
                visual_result="pass",
                visual_notes=["subject/action/camera/style checked"],
                expected_profile="balanced",
                required_rules=["tag_conflict"],
                expect_tokens=["bare_feet"],
                reject_tokens=["high_heels"],
                intentional_differences=[
                    {"path": "$.input", "reason": "policy rewrote prompt"},
                    {"path": "$.parameters.prompt", "reason": "policy rewrote prompt"},
                ],
            )

        self.assertEqual(report["result"], "pass")
        self.assertTrue(report["acceptance_ready"])
        self.assertEqual(report["policy"]["trace_count"], 1)
        self.assertEqual(report["legacy_core_parameter_diff"]["unapproved_diff_count"], 0)
        self.assertEqual(report["core_request_vs_png"]["diff_count"], 0)
        self.assertEqual(report["generation_png_info_vs_png"]["diff_count"], 0)
        self.assertTrue(report["tokens"]["expected_tokens_present"])
        self.assertTrue(report["tokens"]["rejected_tokens_absent"])
        self.assertEqual(report["visual"]["result"], "pass")

    def test_prompt_policy_acceptance_requires_visual_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = "1girl, bare_feet"
            legacy_image = root / "legacy.png"
            core_image = root / "core.png"
            legacy_image.write_bytes(_png_bytes_with_text({"Comment": json.dumps(_params(prompt))}))
            core_image.write_bytes(_png_bytes_with_text({"Comment": json.dumps(_params(prompt))}))
            run_result_path = root / "core_run_result.json"
            run_result_path.write_text(
                json.dumps(
                    {
                        "prompt_bundle": _prompt_bundle(prompt),
                        "generation_result": _generation_result(core_image, prompt),
                    }
                ),
                encoding="utf-8",
            )

            report = build_prompt_policy_acceptance_report(
                legacy_image=legacy_image,
                core_run_result=run_result_path,
                visual_result="pending",
            )

        self.assertEqual(report["result"], "fail")
        self.assertFalse(report["acceptance_ready"])
        self.assertIn(
            "visual_result must be pass for PromptPolicyPipeline acceptance",
            report["errors"],
        )

    def test_cli_verify_prompt_policy_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = "1girl, bare_feet"
            legacy_image = root / "legacy.png"
            core_image = root / "core.png"
            run_result_path = root / "core_run_result.json"
            legacy_image.write_bytes(_png_bytes_with_text({"Comment": json.dumps(_params(prompt))}))
            core_image.write_bytes(_png_bytes_with_text({"Comment": json.dumps(_params(prompt))}))
            run_result_path.write_text(
                json.dumps(
                    {
                        "prompt_bundle": _prompt_bundle(prompt),
                        "generation_result": _generation_result(core_image, prompt),
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "verify-prompt-policy-acceptance",
                        "--legacy-image",
                        str(legacy_image),
                        "--core-run-result",
                        str(run_result_path),
                        "--visual-result",
                        "pass",
                        "--expected-profile",
                        "balanced",
                        "--require-policy-rule",
                        "tag_conflict",
                        "--expect-token",
                        "bare_feet",
                        "--reject-token",
                        "high_heels",
                    ]
                )
            data = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["schema"], "tags-machine-core.prompt-policy-acceptance/v1")
        self.assertEqual(data["result"], "pass")


if __name__ == "__main__":
    unittest.main()
