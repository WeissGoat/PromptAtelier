from __future__ import annotations

import io
import zipfile
import unittest

from tags_machine_core.clients import NovelAIClient, NovelAIClientError
from tags_machine_core.contracts import RenderRequest


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", text: str = "OK"):
        self.status_code = status_code
        self.content = content
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("raise_for_status should not be called for error path in this test")


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.response


def build_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zipped:
        zipped.writestr("image_1.png", b"png-bytes-1")
        zipped.writestr("image_2.png", b"png-bytes-2")
    return buf.getvalue()


class NovelAIClientTest(unittest.TestCase):
    def test_build_payload_and_extract_images(self):
        session = FakeSession(FakeResponse(200, content=build_zip_bytes()))
        client = NovelAIClient(access_token="token", http_client=session, retry=1)
        request = RenderRequest(
            backend="novelai",
            prompt="girl, standing",
            negative_prompt="bad anatomy",
            model="nai-diffusion-4-5-full",
            meta={"action": "generate"},
            params={
                "reference_image_multiple": ["x" * 100],
                "director_reference_images": ["director-x"],
                "seed": 123,
            },
        )

        payload = client.build_payload(request)
        self.assertEqual(payload["input"], "girl, standing")
        self.assertEqual(payload["model"], "nai-diffusion-4-5-full")
        self.assertEqual(payload["action"], "generate")
        self.assertEqual(payload["parameters"]["director_reference_images"], ["director-x"])

        images = client.generate_images(request)
        self.assertEqual([image.filename for image in images], ["image_1.png", "image_2.png"])
        self.assertEqual([image.content for image in images], [b"png-bytes-1", b"png-bytes-2"])
        self.assertEqual(session.calls[0]["url"], "https://image.novelai.net/ai/generate-image")
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer token")
        self.assertEqual(session.calls[0]["headers"]["Origin"], "https://novelai.net")
        self.assertEqual(session.calls[0]["headers"]["Referer"], "https://novelai.net")
        self.assertEqual(session.calls[0]["timeout"], 120)

    def test_build_payload_filters_runtime_only_parameters(self):
        client = NovelAIClient(access_token="token", http_client=FakeSession(FakeResponse(200)), retry=1)
        request = RenderRequest(
            backend="novelai",
            prompt="girl, standing",
            model="nai-diffusion-4-5-full",
            params={
                "seed": 123,
                "steps": 28,
                "reference_image_multiple": [],
                "reference_strength_multiple": [],
                "reference_information_extracted_multiple": [],
                "director_reference_images": [],
                "png_text": {"Comment": "debug only"},
                "model": "debug duplicate",
                "prompt": "debug duplicate",
                "unknown_field": "debug only",
                "cfg_rescale": None,
            },
        )

        payload = client.build_payload(request)

        self.assertEqual(payload["parameters"]["seed"], 123)
        self.assertEqual(payload["parameters"]["steps"], 28)
        self.assertNotIn("reference_image_multiple", payload["parameters"])
        self.assertNotIn("reference_strength_multiple", payload["parameters"])
        self.assertNotIn("reference_information_extracted_multiple", payload["parameters"])
        self.assertNotIn("director_reference_images", payload["parameters"])
        self.assertNotIn("png_text", payload["parameters"])
        self.assertNotIn("model", payload["parameters"])
        self.assertNotIn("prompt", payload["parameters"])
        self.assertNotIn("unknown_field", payload["parameters"])
        self.assertNotIn("cfg_rescale", payload["parameters"])

    def test_error_keeps_payload_sanitized(self):
        session = FakeSession(FakeResponse(400, text="bad request"))
        client = NovelAIClient(access_token="token", http_client=session, retry=1)
        request = RenderRequest(
            backend="novelai",
            prompt="girl, standing",
            params={"reference_image_multiple": ["x" * 1000]},
        )

        with self.assertRaises(NovelAIClientError) as ctx:
            client.generate_image_zip(request)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("bad request", ctx.exception.response_text)
        self.assertLess(len(ctx.exception.sanitized_payload["parameters"]["reference_image_multiple"][0]), 200)


if __name__ == "__main__":
    unittest.main()
