import io
import json
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path

from tags_machine_core.cli import main
from tags_machine_core.verification import (
    compare_render_parameters,
    normalize_render_parameters,
    read_image_parameters,
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


if __name__ == "__main__":
    unittest.main()
