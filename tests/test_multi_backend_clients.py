from __future__ import annotations

import base64
import unittest

from tags_machine_core.clients import (
    ComfyUIClient,
    ComfyUIClientError,
    SDClient,
    SDClientError,
)
from tags_machine_core.contracts import RenderRequest


class FakeJsonResponse:
    def __init__(self, status_code: int, data=None, text: str = "OK"):
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self):
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("raise_for_status should not be called for error paths")


class FakePostSession:
    def __init__(self, response: FakeJsonResponse):
        self.response = response
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self.response


class MultiBackendClientTest(unittest.TestCase):
    def test_comfyui_client_applies_overrides_and_queues_prompt(self):
        session = FakePostSession(FakeJsonResponse(200, data={"prompt_id": "abc123"}))
        client = ComfyUIClient(base_url="http://comfy.local", timeout=30, http_client=session)
        request = RenderRequest(
            backend="comfyui",
            prompt="akemi homura",
            params={
                "workflow_json": {
                    "12": {"inputs": {"cfg": 5.0}},
                    "17": {"inputs": {"text": ""}},
                },
                "node_overrides": {
                    "12.inputs.cfg": 6.5,
                    "17.inputs.text": "akemi homura",
                },
            },
        )

        payload = client.build_payload(request, client_id="client-1")
        result = client.queue_prompt(request, client_id="client-1")

        self.assertEqual(payload["client_id"], "client-1")
        self.assertEqual(payload["prompt"]["12"]["inputs"]["cfg"], 6.5)
        self.assertEqual(payload["prompt"]["17"]["inputs"]["text"], "akemi homura")
        self.assertEqual(result.prompt_id, "abc123")
        self.assertEqual(session.calls[0]["url"], "http://comfy.local/prompt")
        self.assertEqual(session.calls[0]["timeout"], 30)

    def test_comfyui_client_requires_workflow_mapping(self):
        client = ComfyUIClient()
        request = RenderRequest(
            backend="comfyui",
            prompt="akemi homura",
            params={"workflow": "portrait_workflow"},
        )

        with self.assertRaises(ValueError):
            client.build_payload(request)

    def test_comfyui_client_accepts_empty_workflow_json(self):
        client = ComfyUIClient()
        request = RenderRequest(
            backend="comfyui",
            prompt="akemi homura",
            params={"workflow_json": {}},
        )

        payload = client.build_payload(request)

        self.assertEqual(payload["prompt"], {})

    def test_comfyui_client_error_keeps_payload_sanitized(self):
        session = FakePostSession(FakeJsonResponse(400, data={"error": "bad"}, text="bad request"))
        client = ComfyUIClient(http_client=session)
        request = RenderRequest(
            backend="comfyui",
            prompt="akemi homura",
            params={
                "workflow_json": {
                    "1": {"inputs": {"image": "x" * 1000}},
                }
            },
        )

        with self.assertRaises(ComfyUIClientError) as ctx:
            client.queue_prompt(request)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("bad request", ctx.exception.response_text)
        image = ctx.exception.sanitized_payload["prompt"]["1"]["inputs"]["image"]
        self.assertLess(len(image), 200)

    def test_sd_client_builds_txt2img_payload_and_decodes_images(self):
        image_bytes = b"png-bytes"
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        session = FakePostSession(FakeJsonResponse(200, data={"images": [image_base64]}))
        client = SDClient(base_url="http://sd.local", timeout=45, http_client=session)
        request = RenderRequest(
            backend="sd",
            prompt="akemi homura",
            negative_prompt="bad anatomy",
            seed=123,
            size={"width": 832, "height": 1216},
            params={
                "checkpoint": "anime_sd.safetensors",
                "vae": "anime.vae.pt",
                "clip_skip": 2,
                "steps": 24,
                "cfg_scale": 7.5,
                "sampler": "DPM++ 2M",
                "scheduler": "karras",
                "hires_fix": {
                    "enabled": True,
                    "scale": 1.5,
                    "upscaler": "Latent",
                    "steps": 8,
                    "denoising_strength": 0.35,
                },
                "controlnet": [{"enabled": False}],
                "extra_payload": {"restore_faces": False},
            },
        )

        payload = client.build_payload(request)
        images = client.generate_images(request)

        self.assertEqual(payload["prompt"], "akemi homura")
        self.assertEqual(payload["negative_prompt"], "bad anatomy")
        self.assertEqual(payload["seed"], 123)
        self.assertEqual(payload["width"], 832)
        self.assertEqual(payload["height"], 1216)
        self.assertEqual(payload["steps"], 24)
        self.assertEqual(payload["cfg_scale"], 7.5)
        self.assertEqual(payload["sampler_name"], "DPM++ 2M")
        self.assertEqual(payload["scheduler"], "karras")
        self.assertEqual(payload["override_settings"]["sd_model_checkpoint"], "anime_sd.safetensors")
        self.assertEqual(payload["override_settings"]["sd_vae"], "anime.vae.pt")
        self.assertEqual(payload["override_settings"]["CLIP_stop_at_last_layers"], 2)
        self.assertTrue(payload["enable_hr"])
        self.assertEqual(payload["hr_scale"], 1.5)
        self.assertEqual(payload["alwayson_scripts"]["controlnet"]["args"], [{"enabled": False}])
        self.assertFalse(payload["restore_faces"])
        self.assertEqual(images[0].filename, "sd_123_01.png")
        self.assertEqual(images[0].content, image_bytes)
        self.assertEqual(session.calls[0]["url"], "http://sd.local/sdapi/v1/txt2img")
        self.assertEqual(session.calls[0]["timeout"], 45)

    def test_sd_client_error_keeps_payload_sanitized(self):
        session = FakePostSession(FakeJsonResponse(500, data={}, text="server error"))
        client = SDClient(http_client=session)
        request = RenderRequest(
            backend="sd",
            prompt="x" * 3000,
            params={"steps": 20},
        )

        with self.assertRaises(SDClientError) as ctx:
            client.txt2img(request)

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("server error", ctx.exception.response_text)
        self.assertLess(len(ctx.exception.sanitized_payload["prompt"]), 2100)


if __name__ == "__main__":
    unittest.main()
