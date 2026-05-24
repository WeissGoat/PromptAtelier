import json
import tempfile
import unittest
from pathlib import Path

from tags_machine_core.composers import ScriptComposer
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.renderers import ComfyUIRenderAdapter, NovelAIRenderAdapter, SDRenderAdapter
from tags_machine_core.services import GenerationService


def _bundle():
    return ScriptComposer().compose_full_prompt(
        prompt="akemi homura, foot focus",
        negative="extra toes",
        style_ref="cross_backend_style",
    )


def _style_node() -> NodeDocument:
    return NodeDocument.model_validate(
        {
            "schema": "tags-machine-core.node/v1",
            "kind": "style",
            "id": "cross_backend_style",
            "tags": {
                "style": ["anime style"],
                "quality": ["{best quality}"],
            },
            "negative_prompt": ["lowres"],
            "renderers": {
                "novelai": {
                    "prompt_prefix": ["style prefix"],
                    "prompt_suffix": ["style suffix"],
                    "negative_prompt": ["bad anatomy"],
                    "params": {
                        "sampler": "k_euler_ancestral",
                        "noise_schedule": "karras",
                        "steps": 30,
                        "reference_image_multiple": ["abc"],
                        "reference_strength_multiple": [0.25],
                    },
                },
                "comfyui": {
                    "workflow": "portrait_workflow",
                    "checkpoint": "anime_comfy.safetensors",
                    "loras": [{"name": "lineart", "weight": 0.65}],
                    "params": {"steps": 32, "cfg": 6.5},
                },
                "sd": {
                    "checkpoint": "anime_sd.safetensors",
                    "vae": "anime.vae.pt",
                    "loras": [{"name": "feet_detail", "weight": 0.8}],
                    "params": {"steps": 24, "cfg_scale": 7.5},
                },
            },
        }
    )


class MultiBackendRendererTest(unittest.TestCase):
    def test_novelai_adapter_accepts_structured_style_node(self):
        request = NovelAIRenderAdapter().build_request(
            _bundle(),
            seed=321,
            style=_style_node(),
        )

        self.assertEqual(request.backend, "novelai")
        self.assertEqual(request.params["steps"], 30)
        self.assertEqual(request.params["reference_image_multiple"], ["abc"])
        self.assertEqual(request.params["reference_strength_multiple"], [0.25])
        self.assertIn("style prefix", request.prompt)
        self.assertIn("akemi homura, foot focus", request.prompt)
        self.assertIn("anime style", request.prompt)
        self.assertIn("{best quality}", request.prompt)
        self.assertIn("style suffix", request.prompt)
        self.assertIn("extra toes", request.negative_prompt)
        self.assertIn("lowres", request.negative_prompt)
        self.assertIn("bad anatomy", request.negative_prompt)

    def test_comfyui_adapter_builds_dry_run_render_request(self):
        request = ComfyUIRenderAdapter().build_request(
            _bundle(),
            seed=123,
            width=832,
            height=1216,
            style=_style_node(),
            params={"scheduler": "karras"},
        )

        self.assertEqual(request.backend, "comfyui")
        self.assertEqual(request.model, "anime_comfy.safetensors")
        self.assertEqual(request.seed, 123)
        self.assertEqual(request.params["workflow"], "portrait_workflow")
        self.assertEqual(request.params["steps"], 32)
        self.assertEqual(request.params["cfg"], 6.5)
        self.assertEqual(request.params["scheduler"], "karras")
        self.assertEqual(request.params["loras"], [{"name": "lineart", "weight": 0.65}])
        self.assertEqual(request.params["positive_prompt"], "akemi homura, foot focus")
        self.assertEqual(request.params["negative_prompt"], "extra toes")
        self.assertEqual(request.meta["backend"], "comfyui")

    def test_comfyui_adapter_uses_inline_workflow_json(self):
        workflow = {"1": {"inputs": {"text": "before"}}}
        style = _style_node().model_copy(deep=True)
        style.renderers["comfyui"]["workflow"] = "inline_workflow"
        style.renderers["comfyui"]["workflow_json"] = workflow

        request = ComfyUIRenderAdapter().build_request(_bundle(), style=style)
        workflow["1"]["inputs"]["text"] = "after"

        self.assertEqual(request.params["workflow"], "inline_workflow")
        self.assertEqual(request.params["workflow_json"]["1"]["inputs"]["text"], "before")

    def test_comfyui_adapter_loads_workflow_json_relative_to_style_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            style_dir = Path(tmp) / "style"
            workflow_dir = style_dir / "workflows"
            workflow_dir.mkdir(parents=True)
            workflow_path = workflow_dir / "portrait.json"
            workflow_path.write_text(
                json.dumps({"12": {"inputs": {"cfg": 6.5}}}),
                encoding="utf-8",
            )
            style = _style_node().model_copy(update={"path": style_dir}, deep=True)
            style.renderers["comfyui"]["workflow"] = "portrait_workflow"
            style.renderers["comfyui"]["workflow_path"] = "workflows/portrait.json"

            request = ComfyUIRenderAdapter().build_request(_bundle(), style=style)

            self.assertEqual(request.params["workflow"], "portrait_workflow")
            self.assertEqual(request.params["workflow_json"]["12"]["inputs"]["cfg"], 6.5)

    def test_comfyui_adapter_resolves_node_override_templates(self):
        style = _style_node().model_copy(deep=True)
        style.renderers["comfyui"]["node_overrides"] = {
            "2.inputs.text": "{positive_prompt}",
            "3.inputs.text": "{negative_prompt}",
            "4.inputs.width": "{width}",
            "4.inputs.height": "{height}",
            "5.inputs.seed": "{seed}",
            "5.inputs.steps": "{steps}",
            "5.inputs.cfg": "{cfg}",
            "7.inputs.filename_prefix": "tmc_{seed}_{width}x{height}",
        }

        request = ComfyUIRenderAdapter().build_request(
            _bundle(),
            seed=123,
            width=832,
            height=1216,
            style=style,
        )

        overrides = request.params["node_overrides"]
        self.assertEqual(overrides["2.inputs.text"], "akemi homura, foot focus")
        self.assertEqual(overrides["3.inputs.text"], "extra toes")
        self.assertEqual(overrides["4.inputs.width"], 832)
        self.assertEqual(overrides["4.inputs.height"], 1216)
        self.assertEqual(overrides["5.inputs.seed"], 123)
        self.assertEqual(overrides["5.inputs.steps"], 32)
        self.assertEqual(overrides["5.inputs.cfg"], 6.5)
        self.assertEqual(overrides["7.inputs.filename_prefix"], "tmc_123_832x1216")

    def test_sd_adapter_builds_dry_run_render_request(self):
        request = SDRenderAdapter().build_request(
            _bundle(),
            seed=456,
            width=768,
            height=1024,
            style=_style_node(),
            params={"sampler": "DPM++ 2M", "clip_skip": 2},
        )

        self.assertEqual(request.backend, "sd")
        self.assertEqual(request.model, "anime_sd.safetensors")
        self.assertEqual(request.seed, 456)
        self.assertEqual(request.params["checkpoint"], "anime_sd.safetensors")
        self.assertEqual(request.params["steps"], 24)
        self.assertEqual(request.params["cfg_scale"], 7.5)
        self.assertEqual(request.params["sampler"], "DPM++ 2M")
        self.assertEqual(request.params["clip_skip"], 2)
        self.assertEqual(request.params["vae"], "anime.vae.pt")
        self.assertEqual(request.params["loras"], [{"name": "feet_detail", "weight": 0.8}])
        self.assertEqual(request.meta["backend"], "sd")

    def test_generation_service_dispatches_backend_adapters(self):
        service = GenerationService()
        comfy = service.build_render_request(
            _bundle(),
            backend="comfyui",
            seed=1,
            style=_style_node(),
        )
        sd = service.build_render_request(
            _bundle(),
            backend="sd",
            seed=2,
            style=_style_node(),
        )

        self.assertEqual(comfy.backend, "comfyui")
        self.assertEqual(sd.backend, "sd")

    def test_generation_service_dispatches_structured_style_to_novelai(self):
        request = GenerationService().build_render_request(
            _bundle(),
            backend="novelai",
            seed=3,
            style=_style_node(),
        )

        self.assertEqual(request.backend, "novelai")
        self.assertIn("style prefix", request.prompt)
        self.assertIn("anime style", request.prompt)


if __name__ == "__main__":
    unittest.main()
