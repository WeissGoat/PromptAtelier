import base64
import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase

from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from tags_machine_core.web import create_app


class WebImageMetaTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)
        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_test_png(
        self,
        path: Path,
        *,
        prompt: str = "1girl, solo, school uniform",
        negative_prompt: str = "lowres, bad anatomy",
        seed: int = 12345678,
        width: int = 128,
        height: int = 256,
        steps: int = 28,
        scale: float = 5.0,
        sampler: str = "k_euler",
        model: str = "nai-diffusion-3",
        include_meta: bool = True,
    ) -> bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        png_info = PngInfo()
        if include_meta:
            comment_data = {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "seed": seed,
                "steps": steps,
                "scale": scale,
                "sampler": sampler,
                "model": model,
                "width": width,
                "height": height,
            }
            png_info.add_text("Comment", json.dumps(comment_data))
            png_info.add_text("Source", "NovelAI V3")

        img = Image.new("RGB", (width, height), "white")
        img.save(path, format="PNG", pnginfo=png_info)
        return path.read_bytes()

    def test_inspect_image_meta_with_server_path(self):
        png_path = self.tmp_path / "test_sample.png"
        self._create_test_png(png_path, prompt="masterpiece, 1girl", seed=987654)

        response = self.client.post("/api/image-meta/inspect", json={"path": str(png_path)})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()

        self.assertEqual(data["prompt"], "masterpiece, 1girl")
        self.assertEqual(data["seed"], 987654)
        self.assertEqual(data["dimensions"], {"width": 128, "height": 256})
        self.assertEqual(data["steps"], 28)
        self.assertEqual(data["scale"], 5.0)
        self.assertEqual(data["sampler"], "k_euler")
        self.assertEqual(data["model"], "nai-diffusion-3")
        self.assertEqual(data["filename"], "test_sample.png")

    def test_inspect_image_meta_with_upload_file(self):
        png_path = self.tmp_path / "upload_sample.png"
        png_bytes = self._create_test_png(
            png_path,
            prompt="cyberpunk city, neon lights",
            negative_prompt="blurry",
            seed=445566,
            width=64,
            height=64,
        )

        response = self.client.post(
            "/api/image-meta/inspect",
            files={"file": ("upload_sample.png", io.BytesIO(png_bytes), "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()

        self.assertEqual(data["prompt"], "cyberpunk city, neon lights")
        self.assertEqual(data["negative_prompt"], "blurry")
        self.assertEqual(data["seed"], 445566)
        self.assertEqual(data["dimensions"], {"width": 64, "height": 64})
        self.assertEqual(data["filename"], "upload_sample.png")

    def test_inspect_image_meta_with_base64(self):
        png_path = self.tmp_path / "b64_sample.png"
        png_bytes = self._create_test_png(
            png_path,
            prompt="space station, stars",
            seed=778899,
            width=80,
            height=80,
        )
        b64_data = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

        response = self.client.post(
            "/api/image-meta/inspect",
            json={"image_base64": b64_data, "filename": "b64_sample.png"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()

        self.assertEqual(data["prompt"], "space station, stars")
        self.assertEqual(data["seed"], 778899)
        self.assertEqual(data["dimensions"], {"width": 80, "height": 80})

    def test_inspect_image_meta_fallback_non_metadata(self):
        png_path = self.tmp_path / "plain.png"
        png_bytes = self._create_test_png(png_path, width=50, height=80, include_meta=False)

        response = self.client.post(
            "/api/image-meta/inspect",
            files={"file": ("plain.png", io.BytesIO(png_bytes), "image/png")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()

        self.assertEqual(data["prompt"], "")
        self.assertEqual(data["negative_prompt"], "")
        self.assertIsNone(data["seed"])
        self.assertEqual(data["dimensions"], {"width": 50, "height": 80})
        self.assertEqual(data["filename"], "plain.png")

    def test_inspect_image_meta_invalid_request(self):
        response = self.client.post("/api/image-meta/inspect", json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "missing_image_source")

    def test_inspect_image_meta_normalizes_v45_source_model(self):
        png_path = self.tmp_path / "v45_source.png"
        png_info = PngInfo()
        png_info.add_text("Source", "NovelAI Diffusion V4.5 4BDE2A90")
        img = Image.new("RGB", (64, 64), "white")
        img.save(png_path, format="PNG", pnginfo=png_info)

        response = self.client.post("/api/image-meta/inspect", json={"path": str(png_path)})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["model"], "nai-diffusion-4-5-full")
