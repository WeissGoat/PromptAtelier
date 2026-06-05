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
    execute_comfyui_generation,
    execute_novelai_generation,
    execute_render_request,
    execute_sd_generation,
    save_generated_images,
)
from tags_machine_core.verification import read_png_text_chunks


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
            "comfyui": {
                "base_url": "http://comfy.local",
                "timeout": 31,
            },
            "sd": {
                "base_url": "http://sd.local",
                "timeout": 32,
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

    def test_save_generated_images_writes_core_png_text_without_touching_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_bytes = _png_bytes_with_text(
                {
                    "Comment": json.dumps({"prompt": "akemi homura", "seed": 123}),
                    "Source": "NovelAI V4.5",
                }
            )
            request = RenderRequest(
                backend="novelai",
                prompt="akemi homura",
                model="nai-diffusion-4-5-full",
                seed=123,
                artist_payload={"path": "design/画风/20260412"},
                meta={
                    "mode": "run-prompt",
                    "composer_type": "agent",
                    "composer_version": "v1",
                    "prompt_cache_key": "sha256:abc",
                    "resolution": "portrait",
                    "split_batch": {"index": 0, "count": 3, "reason": "random_resolution"},
                    "node_refs": [
                        {"role": "character", "id": "homura", "ref": "design/角色/homura"},
                        {"role": "artist", "id": "20260412", "ref": "20260412"},
                    ],
                    "character_prompts": {"mode": "auto", "count": 1},
                },
            )

            images = save_generated_images(
                [SimpleNamespace(filename="nai.png", content=image_bytes)],
                output_dir=root,
                request=request,
                default_format="png",
            )
            chunks = read_png_text_chunks(images[0].path)
            core_info = json.loads(chunks["tags_machine_core"])

            self.assertEqual(json.loads(chunks["Comment"])["seed"], 123)
            self.assertEqual(chunks["mode"], "run-prompt")
            self.assertEqual(chunks["artist"], "20260412")
            self.assertEqual(chunks["artist_path"], "design/画风/20260412")
            self.assertEqual(chunks["character"], "design/角色/homura")
            self.assertEqual(core_info["schema"], "tags-machine-core.png-info/v1")
            self.assertEqual(core_info["nodes"][1]["role"], "artist")
            self.assertEqual(core_info["character_prompts"]["mode"], "auto")
            self.assertEqual(core_info["resolution"], "portrait")
            self.assertEqual(core_info["split_batch"]["count"], 3)

    def test_execute_novelai_generation_splits_batch_samples_before_requesting(self):
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
                client.build_payload.side_effect = lambda split_request: {
                    "input": split_request.prompt,
                    "model": split_request.model,
                    "action": "generate",
                    "parameters": dict(split_request.params),
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
            self.assertEqual(client.generate_images.call_count, 2)
            called_requests = [item.args[0] for item in client.generate_images.call_args_list]
            self.assertEqual([item.params["n_samples"] for item in called_requests], [1, 1])
            self.assertEqual([item.params["seed"] for item in called_requests], [111, 112])
            self.assertEqual(client.build_payload.call_count, 2)
            self.assertEqual(result.backend, "novelai")
            self.assertTrue(result.request_body["split_batch"])
            self.assertEqual(
                [item["parameters"]["n_samples"] for item in result.request_body["requests"]],
                [1, 1],
            )
            self.assertEqual(
                [item["parameters"]["seed"] for item in result.request_body["requests"]],
                [111, 112],
            )
            self.assertEqual(len(result.images), 2)
            self.assertEqual(result.images[0].path.parent, output_dir)
            self.assertEqual(result.images[0].path.read_bytes(), b"image-bytes")
            self.assertEqual(result.images[1].meta["split_request_index"], 1)
            self.assertIn("Not a PNG file", result.png_info["images"][0]["error"])
            self.assertEqual(result.png_info["images"][1]["split_request_index"], 1)

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

    def test_execute_render_request_rejects_experimental_backend_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _app_config(Path(tmp))
            request = RenderRequest(
                backend="comfyui",
                prompt="akemi homura",
                params={"workflow_json": {}},
            )

            with (
                patch("tags_machine_core.execution.ComfyUIClient") as client_cls,
                self.assertRaises(ValueError) as raised,
            ):
                execute_render_request(
                    config,
                    request,
                    output_dir=None,
                    image_format="png",
                )

            self.assertIn("only NovelAI by default", str(raised.exception))
            client_cls.assert_not_called()

    def test_execute_render_request_routes_novelai_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _app_config(Path(tmp))
            request = RenderRequest(
                backend="novelai",
                prompt="akemi homura",
            )

            with patch("tags_machine_core.execution.execute_novelai_generation") as execute:
                execute.return_value = SimpleNamespace(backend="novelai")
                result = execute_render_request(
                    config,
                    request,
                    output_dir="custom_outputs",
                    image_format="webp",
                )

            self.assertEqual(result.backend, "novelai")
            execute.assert_called_once_with(
                config,
                request,
                output_dir="custom_outputs",
                image_format="webp",
            )

    def test_execute_comfyui_generation_can_queue_without_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _app_config(Path(tmp))
            request = RenderRequest(
                backend="comfyui",
                prompt="akemi homura",
                params={"workflow_json": {"1": {"inputs": {"text": "akemi homura"}}}},
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

                result = execute_comfyui_generation(
                    config,
                    request,
                    output_dir=None,
                    image_format="png",
                    client_id="client-1",
                    no_wait=True,
                )

            client_cls.assert_called_once_with(base_url="http://comfy.local", timeout=31)
            client.queue_prompt.assert_called_once_with(request, client_id="client-1")
            client.generate_images.assert_not_called()
            client.build_payload.assert_called_once_with(request, client_id="client-1")
            self.assertEqual(result.backend, "comfyui")
            self.assertEqual(result.images, [])
            self.assertEqual(result.request_body["client_id"], "client-1")
            self.assertEqual(result.png_info["comfyui"]["prompt_id"], "abc123")

    def test_execute_comfyui_generation_saves_images_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "comfy_outputs"
            config = _app_config(root)
            request = RenderRequest(
                backend="comfyui",
                prompt="akemi homura",
                seed=222,
                params={"workflow_json": {"1": {"inputs": {"text": "akemi homura"}}}},
            )
            image_bytes = _png_bytes_with_text(
                {
                    "Comment": json.dumps({"prompt": "akemi homura", "seed": 222}),
                    "Source": "ComfyUI",
                }
            )
            history = {"abc123": {"outputs": {"7": {"images": []}}}}

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
                client.build_payload.return_value = {"prompt": {"1": {}}}

                result = execute_comfyui_generation(
                    config,
                    request,
                    output_dir=output_dir,
                    image_format="png",
                    client_id="client-1",
                    poll_interval=0,
                    max_wait_seconds=1,
                )

            client.generate_images.assert_called_once_with(
                request,
                client_id="client-1",
                poll_interval=0,
                max_wait_seconds=1,
            )
            self.assertEqual(result.backend, "comfyui")
            self.assertEqual(result.png_info["comfyui"]["history"], history)
            self.assertEqual(len(result.images), 1)
            self.assertEqual(result.images[0].path.parent, output_dir)
            self.assertEqual(result.images[0].meta["node_id"], "7")
            self.assertEqual(result.png_info["images"][0]["parameters"]["seed"], 222)
            self.assertEqual(result.png_info["images"][0]["png_text"]["Source"], "ComfyUI")
            self.assertIn("tags_machine_core", result.png_info["images"][0]["png_text"])

    def test_execute_sd_generation_saves_images_and_request_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "sd_outputs"
            config = _app_config(root)
            request = RenderRequest(
                backend="sd",
                prompt="akemi homura",
                seed=321,
                params={"steps": 24},
            )

            with patch("tags_machine_core.execution.SDClient") as client_cls:
                client = client_cls.return_value
                client.generate_images.return_value = [
                    SimpleNamespace(filename="sd_result.png", content=b"png-bytes")
                ]
                client.build_payload.return_value = {"prompt": "akemi homura", "seed": 321}

                result = execute_sd_generation(
                    config,
                    request,
                    output_dir=output_dir,
                    image_format="png",
                )

            client_cls.assert_called_once_with(base_url="http://sd.local", timeout=32)
            client.generate_images.assert_called_once_with(request)
            client.build_payload.assert_called_once_with(request)
            self.assertEqual(result.backend, "sd")
            self.assertEqual(result.request_body["seed"], 321)
            self.assertEqual(result.images[0].path.parent, output_dir)
            self.assertEqual(result.images[0].path.read_bytes(), b"png-bytes")
            self.assertIn("Not a PNG file", result.png_info["images"][0]["error"])


if __name__ == "__main__":
    unittest.main()
