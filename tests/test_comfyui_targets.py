from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from tags_machine_core.batch.runner import _config_with_timeout
from tags_machine_core.clients import PreparedComfyUIWorkflow
from tags_machine_core.config import COMFYUI_TARGET_ENV, AppConfig, ComfyUIConfig, load_config
from tags_machine_core.contracts import PromptBundle, PromptText, RenderRequest
from tags_machine_core.execution import build_comfyui_transport, execute_comfyui_generation
from tags_machine_core.nodes import NodeReader
from tags_machine_core.renderers import ComfyUIRenderAdapter


def _targets_config() -> ComfyUIConfig:
    return ComfyUIConfig.model_validate(
        {
            "timeout": 300,
            "max_wait_seconds": 600,
            "default_target": "local",
            "targets": {
                "local": {},
                "modal": {
                    "base_url": "https://ws--tm-comfyui-api.modal.run",
                    "path_style": "posix",
                    "cold_start_wait_seconds": 300,
                    "allow_no_wait": False,
                    "max_wait_seconds": None,
                    "auth": {"type": "bearer", "token_env": "TM_TEST_COMFY_TOKEN"},
                },
            },
        }
    )


def _app_config(root: Path, comfyui: dict) -> AppConfig:
    return AppConfig.model_validate(
        {
            "legacy": {
                "tags_machine_root": str(root / "legacy"),
                "design_root": str(root / "legacy" / "design"),
            },
            "runtime": {"output_dir": str(root / "outputs")},
            "comfyui": comfyui,
        }
    )


class ComfyUITargetConfigTest(unittest.TestCase):
    def test_legacy_config_resolves_to_default_target(self):
        target = ComfyUIConfig(base_url="http://comfy.local", timeout=31).resolve_target()

        self.assertEqual(target.name, "default")
        self.assertEqual(target.base_url, "http://comfy.local")
        self.assertEqual(target.timeout, 31)
        self.assertEqual(target.path_style, "native")

    def test_targets_inherit_top_level_fields(self):
        config = _targets_config()

        local = config.resolve_target()
        modal = config.resolve_target("modal")

        self.assertEqual(local.name, "local")
        self.assertEqual(local.base_url, "http://127.0.0.1:8188")
        self.assertEqual(local.max_wait_seconds, 600)
        self.assertEqual(modal.timeout, 300)
        self.assertEqual(modal.path_style, "posix")
        self.assertIsNone(modal.max_wait_seconds)
        self.assertFalse(modal.allow_no_wait)

    def test_several_targets_require_a_default(self):
        config = _targets_config().model_copy(update={"default_target": None})

        with self.assertRaises(ValueError) as raised:
            config.resolve_target()

        self.assertIn(COMFYUI_TARGET_ENV, str(raised.exception))

    def test_unknown_target_lists_choices(self):
        with self.assertRaises(ValueError) as raised:
            _targets_config().resolve_target("runpod")

        self.assertIn("local, modal", str(raised.exception))

    def test_target_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError):
            ComfyUIConfig.model_validate({"targets": {"modal": {"base-url": "https://x"}}})

    def test_with_timeout_updates_targets_that_set_their_own(self):
        config = ComfyUIConfig.model_validate(
            {"timeout": 300, "targets": {"a": {}, "b": {"timeout": 900}}, "default_target": "a"}
        )

        updated = config.with_timeout(600)

        self.assertEqual(updated.resolve_target("a").timeout, 600)
        self.assertEqual(updated.resolve_target("b").timeout, 600)

    def test_batch_timeout_override_reaches_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _app_config(Path(tmp), {"targets": {"modal": {"timeout": 900}}})

            updated = _config_with_timeout(config, 120)

        self.assertEqual(updated.comfyui.resolve_target("modal").timeout, 120)

    def test_env_var_selects_target_when_loading_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                "legacy:\n"
                f"  tags_machine_root: {tmp}\n"
                f"  design_root: {tmp}\n"
                "comfyui:\n"
                "  default_target: local\n"
                "  targets:\n"
                "    local: {}\n"
                "    modal: {base_url: 'https://modal.example'}\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {COMFYUI_TARGET_ENV: "modal"}):
                config = load_config(path)

        self.assertEqual(config.comfyui.resolve_target().base_url, "https://modal.example")


class ComfyUITargetExecutionTest(unittest.TestCase):
    def test_transport_gets_bearer_header_from_env(self):
        target = _targets_config().resolve_target("modal")

        with patch.dict(os.environ, {"TM_TEST_COMFY_TOKEN": "wk-1.ws-2"}):
            transport = build_comfyui_transport(target)

        self.assertEqual(transport.headers, {"Authorization": "Bearer wk-1.ws-2"})
        self.assertEqual(transport.path_style, "posix")
        self.assertEqual(transport.ready_timeout, 300)

    def test_missing_token_names_the_env_var(self):
        target = _targets_config().resolve_target("modal")

        with patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError) as raised:
            build_comfyui_transport(target)

        self.assertIn("TM_TEST_COMFY_TOKEN", str(raised.exception))

    def test_header_envs_support_provider_specific_schemes(self):
        config = ComfyUIConfig.model_validate(
            {"auth": {"header_envs": {"Modal-Key": "TM_KEY", "Modal-Secret": "TM_SECRET"}}}
        )

        with patch.dict(os.environ, {"TM_KEY": "wk-1", "TM_SECRET": "ws-2"}):
            transport = build_comfyui_transport(config.resolve_target())

        self.assertEqual(transport.headers, {"Modal-Key": "wk-1", "Modal-Secret": "ws-2"})

    def test_serverless_target_rejects_no_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _app_config(Path(tmp), _targets_config().model_dump())
            request = RenderRequest(backend="comfyui", prompt="x", params={"workflow_json": {}})

            with self.assertRaises(ValueError) as raised:
                execute_comfyui_generation(
                    config,
                    request,
                    output_dir=None,
                    image_format="png",
                    no_wait=True,
                    target="modal",
                )

        self.assertIn("allow_no_wait", str(raised.exception))

    def test_split_batch_archives_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _app_config(Path(tmp), {"base_url": "http://comfy.local"})
            request = RenderRequest(
                backend="comfyui",
                prompt="x",
                seed=10,
                params={"workflow_json": {}, "n_samples": 2},
            )

            with patch("tags_machine_core.execution.ComfyUIClient") as client_cls:
                client = client_cls.return_value
                client.prepare.return_value = PreparedComfyUIWorkflow(prompt={})
                client.queue.return_value = SimpleNamespace(prompt_id="p", raw={})
                client.payload.return_value = {"prompt": {}}

                result = execute_comfyui_generation(
                    config,
                    request,
                    output_dir=None,
                    image_format="png",
                    no_wait=True,
                )

        self.assertEqual(client.queue.call_count, 2)
        self.assertEqual(result.png_info["comfyui"]["target"]["name"], "default")
        self.assertEqual(result.png_info["comfyui"]["workflow_preparation"]["node_count"], 0)


class ComfyUIInputFilesRenderTest(unittest.TestCase):
    def test_input_files_resolve_relative_to_artist_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            node_dir = Path(tmp) / "pose_artist"
            node_dir.mkdir()
            absolute_ref = Path(tmp) / "ref.png"
            (node_dir / "node.yaml").write_text(
                "schema: tags-machine.artist/v1\n"
                "kind: artist\n"
                "id: pose_artist\n"
                "renderers:\n"
                "  comfyui:\n"
                "    workflow_json: {'1': {class_type: LoadImage, inputs: {a: '', b: '', c: 0, d: 0, e: 0}}}\n"
                "    inputs:\n"
                "      positive_prompt: 1.inputs.a\n"
                "      negative_prompt: 1.inputs.b\n"
                "      width: 1.inputs.c\n"
                "      height: 1.inputs.d\n"
                "      seed: 1.inputs.e\n"
                "    input_files:\n"
                "      - inputs/pose.png\n"
                f"      - {{path: '{absolute_ref.as_posix()}', name: r.png, subfolder: tm}}\n",
                encoding="utf-8",
            )
            artist = NodeReader().read(node_dir)

            request = ComfyUIRenderAdapter().build_request(
                PromptBundle(prompt=PromptText(positive="p")),
                artist=artist,
            )

        self.assertEqual(
            request.params["input_files"],
            [
                {"name": "pose.png", "path": str(artist.path / "inputs/pose.png")},
                {"name": "r.png", "path": str(absolute_ref), "subfolder": "tm"},
            ],
        )


if __name__ == "__main__":
    unittest.main()


class ComfyUIProgressAndMetadataTest(unittest.TestCase):
    def test_split_samples_tag_progress_with_their_index(self):
        events: list[dict] = []

        def fake_queue(prepared, *, client_id=None, on_progress=None):
            on_progress("comfyui_queued", {"at": 1.0})
            return SimpleNamespace(prompt_id="p", raw={})

        with tempfile.TemporaryDirectory() as tmp:
            config = _app_config(Path(tmp), {"base_url": "http://comfy.local"})
            request = RenderRequest(
                backend="comfyui", prompt="x", seed=10, params={"workflow_json": {}, "n_samples": 2}
            )
            with patch("tags_machine_core.execution.ComfyUIClient") as client_cls:
                client = client_cls.return_value
                client.prepare.return_value = PreparedComfyUIWorkflow(prompt={})
                client.queue.side_effect = fake_queue
                client.payload.return_value = {"prompt": {}}

                execute_comfyui_generation(
                    config,
                    request,
                    output_dir=None,
                    image_format="png",
                    no_wait=True,
                    on_progress=lambda event, payload: events.append({"type": event, **payload}),
                )

        self.assertEqual(
            [(item["sample_index"], item["sample_count"]) for item in events],
            [(0, 2), (1, 2)],
        )

    def test_comfyui_images_carry_render_parameters(self):
        from tags_machine_core.execution import save_generated_images
        from tags_machine_core.verification import read_image_parameters

        png = (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", (1).to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0]))
            + _chunk(b"IEND", b"")
        )
        request = RenderRequest(
            backend="comfyui",
            prompt="{{x}}, a",
            negative_prompt="[lowres]",
            seed=123,
            size={"width": 832, "height": 1216},
            params={
                "workflow": "cunyfunky",
                "workflow_hash": "sha256:abc",
                "positive_prompt": "(x:1.1), a",
                "negative_prompt": "(lowres:0.95)",
                "prompt_format": "comfyui",
                "cfg": 6.5,
            },
            meta={"comfyui_target": "modal"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            saved = save_generated_images(
                [SimpleNamespace(filename="ComfyUI_00001_.png", content=png)],
                output_dir=Path(tmp),
                request=request,
                default_format="png",
            )
            parameters = read_image_parameters(saved[0].path)["parameters"]

        self.assertEqual(parameters["backend"], "comfyui")
        self.assertEqual(parameters["prompt"], "{{x}}, a")
        self.assertEqual(parameters["comfyui_prompt"], "(x:1.1), a")
        self.assertEqual((parameters["seed"], parameters["width"], parameters["height"]), (123, 832, 1216))
        self.assertEqual(parameters["target"], "modal")
        self.assertEqual(parameters["workflow"], "cunyfunky")
        self.assertEqual(parameters["scale"], 6.5)


def _chunk(kind: bytes, data: bytes) -> bytes:
    import zlib

    return len(data).to_bytes(4, "big") + kind + data + (zlib.crc32(kind + data) & 0xFFFFFFFF).to_bytes(4, "big")
