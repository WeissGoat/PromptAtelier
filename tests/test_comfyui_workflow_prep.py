from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from tags_machine_core.clients import ComfyUIClient, ComfyUIClientError, prepare_comfyui_workflow
from tags_machine_core.comfyui_preflight import comfyui_preflight_report, load_runtime_manifest
from tags_machine_core.contracts import RenderRequest
from tags_machine_core.renderers.comfyui_workflow import (
    normalize_workflow_file_paths,
    prune_workflow_to_outputs,
)


def _workflow() -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base.safetensors"}},
        "10": {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": "风格\\contrast.safetensors",
                "model": ["4", 0],
                "clip": ["4", 1],
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "escaped \\{brace\\}", "clip": ["10", 1]},
        },
        "3": {"class_type": "KSampler", "inputs": {"model": ["10", 0], "positive": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}},
        "20": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "x4.pth"}},
        "21": {"class_type": "PreviewChooser", "inputs": {"images": ["8", 0]}},
        "22": {"class_type": "PreviewImage", "inputs": {"images": ["21", 0]}},
    }


class FakeResponse:
    def __init__(self, status_code: int, data=None, text: str = "", content: bytes = b""):
        self.status_code = status_code
        self._data = data
        self.text = text
        self.content = content

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data

    def raise_for_status(self) -> None:
        pass


class RecordingSession:
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def _next(self, method: str, url: str, kwargs: dict):
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **kwargs):
        return self._next("get", url, kwargs)

    def post(self, url, **kwargs):
        return self._next("post", url, kwargs)


class WorkflowPreparationTest(unittest.TestCase):
    def test_prune_keeps_only_output_ancestors(self):
        pruned, removed = prune_workflow_to_outputs(_workflow(), ["9"])

        self.assertEqual(list(pruned), ["4", "10", "6", "3", "8", "9"])
        self.assertEqual(removed, ["20", "21", "22"])

    def test_prune_rejects_unknown_output_node(self):
        with self.assertRaises(ValueError) as raised:
            prune_workflow_to_outputs(_workflow(), ["999"])

        self.assertIn("999", str(raised.exception))

    def test_posix_normalization_only_touches_relative_file_paths(self):
        workflow = _workflow()
        workflow["4"]["inputs"]["ckpt_name"] = "D:\\models\\abs.safetensors"

        changed = normalize_workflow_file_paths(workflow, "posix")

        self.assertEqual(changed, ["10.inputs.lora_name"])
        self.assertEqual(workflow["10"]["inputs"]["lora_name"], "风格/contrast.safetensors")
        self.assertEqual(workflow["6"]["inputs"]["text"], "escaped \\{brace\\}")
        self.assertEqual(workflow["4"]["inputs"]["ckpt_name"], "D:\\models\\abs.safetensors")

    def test_native_normalization_is_a_no_op(self):
        workflow = _workflow()

        self.assertEqual(normalize_workflow_file_paths(workflow, "native"), [])
        self.assertEqual(workflow["10"]["inputs"]["lora_name"], "风格\\contrast.safetensors")

    def test_prepare_applies_overrides_then_prunes_and_normalizes(self):
        request = RenderRequest(
            backend="comfyui",
            prompt="x",
            params={
                "workflow_json": _workflow(),
                "node_overrides": {"6.inputs.text": "akemi homura"},
                "output_nodes": ["9"],
                "extra_pnginfo": {"workflow": {"nodes": []}},
            },
        )

        prepared = prepare_comfyui_workflow(request, path_style="posix")

        self.assertEqual(prepared.prompt["6"]["inputs"]["text"], "akemi homura")
        self.assertNotIn("21", prepared.prompt)
        self.assertEqual(prepared.pruned_node_ids, ("20", "21", "22"))
        self.assertEqual(prepared.normalized_paths, ("10.inputs.lora_name",))
        self.assertEqual(prepared.extra_data, {"extra_pnginfo": {"workflow": {"nodes": []}}})
        self.assertEqual(request.params["workflow_json"]["6"]["inputs"]["text"], "escaped \\{brace\\}")

    def test_prepare_rejects_bindings_that_miss_the_workflow(self):
        request = RenderRequest(
            backend="comfyui",
            prompt="x",
            params={
                "workflow": "cunyfunky",
                "workflow_json": _workflow(),
                "node_overrides": {"6.inputs.txt": "akemi homura", "99.inputs.seed": 1},
            },
        )

        with self.assertRaises(ValueError) as raised:
            prepare_comfyui_workflow(request)

        message = str(raised.exception)
        self.assertIn("workflow cunyfunky", message)
        self.assertIn("node 6 (CLIPTextEncode) has no input 'txt' (inputs: clip, text)", message)
        self.assertIn("99.inputs.seed: node 99 not found", message)

    def test_prepare_can_opt_out_of_strict_bindings(self):
        request = RenderRequest(
            backend="comfyui",
            prompt="x",
            params={
                "workflow_json": _workflow(),
                "node_overrides": {"6.inputs.new_input": 1},
                "strict_bindings": False,
            },
        )

        prepared = prepare_comfyui_workflow(request)

        self.assertEqual(prepared.prompt["6"]["inputs"]["new_input"], 1)

    def test_prepare_without_output_nodes_keeps_full_workflow(self):
        request = RenderRequest(backend="comfyui", prompt="x", params={"workflow_json": _workflow()})

        prepared = prepare_comfyui_workflow(request)

        self.assertEqual(len(prepared.prompt), 9)
        self.assertEqual(prepared.pruned_node_ids, ())


class NativeClientTargetFeaturesTest(unittest.TestCase):
    def test_headers_are_sent_with_every_request(self):
        session = RecordingSession(
            [
                FakeResponse(200, data={"prompt_id": "p1"}),
                FakeResponse(200, data={"p1": {"outputs": {}, "status": {"completed": True}}}),
            ]
        )
        client = ComfyUIClient(
            base_url="https://comfy.example",
            http_client=session,
            headers={"Authorization": "Bearer wk-1.ws-2"},
        )
        request = RenderRequest(backend="comfyui", prompt="x", params={"workflow_json": {}})

        client.generate_images(request, poll_interval=0, max_wait_seconds=1)

        self.assertEqual(
            [call["headers"]["Authorization"] for call in session.calls],
            ["Bearer wk-1.ws-2", "Bearer wk-1.ws-2"],
        )

    def test_payload_contains_only_pruned_output_subgraph(self):
        client = ComfyUIClient(path_style="posix")
        request = RenderRequest(
            backend="comfyui",
            prompt="x",
            params={"workflow_json": _workflow(), "output_nodes": ["9"]},
        )

        payload = client.build_payload(request)

        self.assertEqual(sorted(payload["prompt"]), ["10", "3", "4", "6", "8", "9"])
        self.assertEqual(payload["prompt"]["10"]["inputs"]["lora_name"], "风格/contrast.safetensors")

    def test_waits_for_cold_start_before_first_prompt(self):
        session = RecordingSession(
            [
                requests.ConnectionError("booting"),
                FakeResponse(503, text="starting"),
                FakeResponse(200, data={"system": {}}),
                FakeResponse(200, data={"prompt_id": "p1"}),
                FakeResponse(200, data={"prompt_id": "p2"}),
            ]
        )
        client = ComfyUIClient(http_client=session, ready_timeout=60)
        request = RenderRequest(backend="comfyui", prompt="x", params={"workflow_json": {}})

        with patch("tags_machine_core.clients.comfyui.time.sleep"):
            first = client.queue_prompt(request)
            second = client.queue_prompt(request)

        self.assertEqual((first.prompt_id, second.prompt_id), ("p1", "p2"))
        self.assertEqual(
            [call["url"].rsplit("/", 1)[-1] for call in session.calls],
            ["system_stats", "system_stats", "system_stats", "prompt", "prompt"],
        )

    def test_run_reports_progress_phases(self):
        session = RecordingSession(
            [
                FakeResponse(200, data={"system": {}}),
                FakeResponse(200, data={"prompt_id": "p1", "number": 3}),
                FakeResponse(200, data={"p1": {"outputs": {}, "status": {"completed": True}}}),
            ]
        )
        client = ComfyUIClient(http_client=session, ready_timeout=60)
        events: list[tuple[str, dict]] = []
        request = RenderRequest(backend="comfyui", prompt="x", params={"workflow_json": {}})

        client.run(
            client.prepare(request),
            poll_interval=0,
            max_wait_seconds=1,
            on_progress=lambda event, payload: events.append((event, payload)),
        )

        self.assertEqual(
            [event for event, _ in events],
            ["comfyui_starting", "comfyui_ready", "comfyui_queued", "comfyui_downloading"],
        )
        queued = dict(events)["comfyui_queued"]
        self.assertEqual((queued["prompt_id"], queued["queue_number"]), ("p1", 3))
        self.assertTrue(all(isinstance(payload["at"], float) for _, payload in events))

    def test_readiness_fails_fast_on_rejected_credentials(self):
        session = RecordingSession([FakeResponse(401, text="missing credentials")])
        client = ComfyUIClient(http_client=session, ready_timeout=60)

        with self.assertRaises(ComfyUIClientError) as raised:
            client.wait_until_ready(60)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertIn("credentials", raised.exception.response_text)

    def test_readiness_times_out(self):
        session = RecordingSession([FakeResponse(503), FakeResponse(503)])
        client = ComfyUIClient(http_client=session)
        # started_at, 每轮的 remaining 和 elapsed 各读一次时钟。
        clock = iter([0.0, 0.0, 0.0, 5.0, 11.0])

        with (
            patch("tags_machine_core.clients.comfyui.time.monotonic", lambda: next(clock)),
            patch("tags_machine_core.clients.comfyui.time.sleep"),
            self.assertRaises(TimeoutError) as raised,
        ):
            client.wait_until_ready(10)

        self.assertIn("HTTP 503", str(raised.exception))

    def test_input_files_are_uploaded_before_queueing(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "pose.png"
            image.write_bytes(b"png-bytes")
            session = RecordingSession(
                [
                    FakeResponse(200, data={"name": "pose.png", "subfolder": "tm", "type": "input"}),
                    FakeResponse(200, data={"prompt_id": "p1"}),
                ]
            )
            client = ComfyUIClient(http_client=session)
            request = RenderRequest(
                backend="comfyui",
                prompt="x",
                params={
                    "workflow_json": {},
                    "input_files": [{"path": str(image), "subfolder": "tm"}],
                },
            )

            client.queue_prompt(request)

        upload, prompt = session.calls
        self.assertTrue(upload["url"].endswith("/upload/image"))
        self.assertEqual(upload["files"]["image"][:2], ("pose.png", b"png-bytes"))
        self.assertEqual(upload["data"], {"type": "input", "subfolder": "tm", "overwrite": "true"})
        self.assertTrue(prompt["url"].endswith("/prompt"))

    def test_upload_rejects_renamed_input_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "pose.png"
            image.write_bytes(b"png-bytes")
            session = RecordingSession([FakeResponse(200, data={"name": "pose (1).png"})])
            client = ComfyUIClient(http_client=session)
            request = RenderRequest(
                backend="comfyui",
                prompt="x",
                params={"workflow_json": {}, "input_files": [{"path": str(image)}]},
            )

            with self.assertRaises(ComfyUIClientError):
                client.queue_prompt(request)


class RuntimeManifestTest(unittest.TestCase):
    def test_models_file_is_merged_into_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.yaml").write_text(
                "custom_nodes: []\nmodels_file: models.yaml\n", encoding="utf-8"
            )
            (root / "models.yaml").write_text(
                "models:\n  - path: loras/a.safetensors\n", encoding="utf-8"
            )

            manifest = load_runtime_manifest(root / "manifest.yaml")

        self.assertEqual(manifest["models"], [{"path": "loras/a.safetensors"}])

    def test_repository_manifest_covers_cunyfunky_models(self):
        manifest = load_runtime_manifest(
            Path(__file__).resolve().parents[1] / "deploy" / "comfyui" / "manifest.yaml"
        )

        self.assertEqual(len(manifest["models"]), 10)
        self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["models"]))


class PreflightReportTest(unittest.TestCase):
    def _prepared(self):
        request = RenderRequest(
            backend="comfyui",
            prompt="x",
            params={"workflow_json": _workflow(), "output_nodes": ["9"]},
        )
        return prepare_comfyui_workflow(request, path_style="posix")

    def test_manifest_check_reports_missing_models(self):
        manifest = {
            "custom_nodes": [{"name": "pack", "provides": ["LoraLoader"]}],
            "models": [{"path": "loras/风格/contrast.safetensors"}],
        }

        report = comfyui_preflight_report(self._prepared(), manifest=manifest)

        self.assertFalse(report["ok"])
        self.assertEqual(
            [item["value"] for item in report["manifest"]["missing_models"]],
            ["base.safetensors"],
        )
        self.assertEqual(report["manifest"]["custom_nodes"], {"LoraLoader": "pack"})
        self.assertNotIn("UpscaleModelLoader", report["class_types"])

    def test_live_check_mirrors_comfyui_validation(self):
        object_info = {
            "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["base.safetensors"]]}}},
            "LoraLoader": {
                "input": {"required": {"lora_name": ["COMBO", {"options": ["风格/other.safetensors"]}]}}
            },
            "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {"multiline": True}]}}},
            "KSampler": {"input": {"required": {}}},
            "VAEDecode": {"input": {"required": {}}},
        }

        report = comfyui_preflight_report(self._prepared(), object_info=object_info)

        self.assertEqual(report["target"]["missing_class_types"], ["SaveImage"])
        self.assertEqual(
            [(item["node"], item["value"]) for item in report["target"]["missing_values"]],
            [("10", "风格/contrast.safetensors")],
        )
        self.assertEqual(len(report["problems"]), 2)


if __name__ == "__main__":
    unittest.main()
