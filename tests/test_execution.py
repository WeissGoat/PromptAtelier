import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tags_machine_core.config import AppConfig
from tags_machine_core.contracts import GeneratedImage, RenderRequest
from tags_machine_core.execution import (
    collect_png_info,
    execute_novelai_generation,
    save_generated_images,
)


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


def _app_config(root: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "legacy": {
                "tags_machine_root": str(root / "legacy"),
                "design_root": str(root / "legacy" / "design"),
            },
            "runtime": {
                "output_dir": str(root / "outputs"),
            },
            "novelai": {
                "base_url": "http://novelai.local",
                "access_token_env": "NAI_ACCESS_TOKEN",
                "timeout": 30,
                "retry": 1,
            },
        }
    )


class ExecutionTest(unittest.TestCase):
    def test_save_generated_images_writes_files_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = RenderRequest(
                backend="novelai",
                prompt="akemi homura",
                seed=2468,
            )

            images = save_generated_images(
                [
                    SimpleNamespace(
                        filename="nai_result",
                        content=b"image-bytes",
                        subfolder="output",
                        image_type="final",
                        node_id="12",
                    )
                ],
                output_dir=root,
                request=request,
                default_format="webp",
            )

            self.assertEqual(len(images), 1)
            self.assertEqual(images[0].path.parent, root)
            self.assertTrue(images[0].filename.endswith("_2468_01.webp"))
            self.assertEqual(images[0].path.read_bytes(), b"image-bytes")
            self.assertEqual(images[0].meta["source_filename"], "nai_result")
            self.assertEqual(images[0].meta["index"], 1)
            self.assertEqual(images[0].meta["subfolder"], "output")
            self.assertEqual(images[0].meta["image_type"], "final")
            self.assertEqual(images[0].meta["node_id"], "12")

    def test_collect_png_info_reads_png_text_and_records_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            png_path = root / "image.png"
            bad_path = root / "image.webp"
            png_path.write_bytes(
                _png_bytes_with_text(
                    {
                        "Comment": json.dumps(
                            {
                                "prompt": "akemi homura",
                                "seed": 123,
                            }
                        ),
                        "Source": "NovelAI V4.5",
                    }
                )
            )
            bad_path.write_bytes(b"not-a-png")

            info = collect_png_info(
                [
                    GeneratedImage(path=png_path, filename="image.png"),
                    GeneratedImage(path=bad_path, filename="image.webp"),
                ]
            )

            self.assertEqual(info["images"][0]["parameters"]["prompt"], "akemi homura")
            self.assertEqual(info["images"][0]["parameters"]["seed"], 123)
            self.assertEqual(info["images"][0]["png_text"]["Source"], "NovelAI V4.5")
            self.assertIn("Not a PNG file", info["images"][1]["error"])

    def test_execute_novelai_generation_uses_config_and_records_request_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "custom_outputs"
            config = _app_config(root)
            request = RenderRequest(
                backend="novelai",
                prompt="akemi homura",
                model="nai-diffusion-4-5-full",
                seed=111,
                params={"seed": 111, "n_samples": 2},
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
                    "parameters": {"seed": 111, "n_samples": 2},
                }

                result = execute_novelai_generation(
                    config,
                    request,
                    output_dir=output_dir,
                    image_format="png",
                )

            client_cls.assert_called_once_with(
                access_token="token",
                base_url="http://novelai.local",
                timeout=30,
                retry=1,
            )
            client.generate_images.assert_called_once_with(request)
            client.build_payload.assert_called_once_with(request)
            self.assertEqual(result.backend, "novelai")
            self.assertEqual(result.request_body["parameters"]["n_samples"], 2)
            self.assertEqual(len(result.images), 1)
            self.assertEqual(result.images[0].path.parent, output_dir)
            self.assertEqual(result.images[0].path.read_bytes(), b"image-bytes")
            self.assertIn("Not a PNG file", result.png_info["images"][0]["error"])

    def test_execute_novelai_generation_requires_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _app_config(root)
            request = RenderRequest(
                backend="novelai",
                prompt="akemi homura",
            )

            with (
                patch.dict("os.environ", {}, clear=True),
                self.assertRaises(RuntimeError) as raised,
            ):
                execute_novelai_generation(
                    config,
                    request,
                    output_dir=None,
                    image_format="png",
                )

            self.assertIn("NAI_ACCESS_TOKEN", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
