import copy
import unittest

from tags_machine_core.contracts import PromptBundle, PromptText
from tags_machine_core.renderers import ComfyUIRenderAdapter, NovelAIRenderAdapter, SDRenderAdapter
from tags_machine_core.renderers.sizes import STANDARD_SIZE_PRESETS, resolve_render_size

P4_PRESETS = {
    "portrait": {"width": 1024, "height": 1536},
    "landscape": {"width": 1536, "height": 1024},
}
COMFY_WORKFLOW = {
    "1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
    "3": {"class_type": "EmptyLatentImage", "inputs": {"width": 0, "height": 0}},
    "4": {"class_type": "KSampler", "inputs": {"seed": 0}},
}


def _artist(backend: str, **fields) -> dict:
    payload = dict(fields)
    if backend == "comfyui":
        payload.update(
            workflow="w",
            workflow_json=copy.deepcopy(COMFY_WORKFLOW),
            inputs={
                "positive_prompt": "1.inputs.text",
                "negative_prompt": "2.inputs.text",
                "width": "3.inputs.width",
                "height": "3.inputs.height",
                "seed": "4.inputs.seed",
            },
        )
    return {"renderers": {backend: payload}}


ADAPTERS = {"novelai": NovelAIRenderAdapter, "comfyui": ComfyUIRenderAdapter, "sd": SDRenderAdapter}


class RenderSizeTest(unittest.TestCase):
    bundle = PromptBundle(prompt=PromptText(positive="x", negative=""))

    def build(self, backend: str, params=None, **artist_fields):
        return ADAPTERS[backend]().build_request(
            self.bundle, seed=1, width=640, height=960, params=params, artist=_artist(backend, **artist_fields)
        )

    def test_every_backend_uses_standard_sizes_when_the_artist_declares_none(self):
        for backend in ADAPTERS:
            with self.subTest(backend=backend):
                portrait = self.build(backend, {"size": "portrait"})
                sizes = {(r.size.width, r.size.height) for r in (self.build(backend, {"size": "random"}) for _ in range(40))}

                self.assertEqual((portrait.size.width, portrait.size.height), (832, 1216))
                self.assertEqual(portrait.meta["size_preset"], "portrait")
                self.assertEqual(sizes, set(STANDARD_SIZE_PRESETS.values()))
                self.assertNotIn("size", portrait.params)

    def test_artist_presets_replace_the_standard_ones(self):
        for backend in ADAPTERS:
            with self.subTest(backend=backend):
                sizes = {
                    (r.size.width, r.size.height, r.meta["size_preset"])
                    for r in (self.build(backend, {"size": "random"}, size_presets=P4_PRESETS) for _ in range(40))
                }
                self.assertEqual(sizes, {(1024, 1536, "portrait"), (1536, 1024, "landscape")})
                with self.assertRaisesRegex(ValueError, "no square size preset"):
                    self.build(backend, {"size": "square"}, size_presets=P4_PRESETS)

    def test_custom_and_missing_choice_keep_the_requested_dimensions(self):
        for backend in ADAPTERS:
            with self.subTest(backend=backend):
                custom = self.build(backend, {"size": "custom"}, size_presets=P4_PRESETS)
                missing = self.build(backend, size_presets=P4_PRESETS)
                defaulted = self.build(backend, size_presets=P4_PRESETS, default_size="landscape")

                self.assertEqual((custom.size.width, custom.size.height), (640, 960))
                self.assertNotIn("size_preset", custom.meta)
                self.assertEqual((missing.size.width, missing.size.height), (640, 960))
                self.assertEqual((defaulted.size.width, defaulted.size.height), (1536, 1024))

    def test_comfyui_binds_the_chosen_size_and_novelai_sends_it(self):
        comfy = self.build("comfyui", {"size": "landscape"}, size_presets=P4_PRESETS)
        novelai = self.build("novelai", {"size": "landscape"})

        self.assertEqual(comfy.params["node_overrides"]["3.inputs.width"], 1536)
        self.assertEqual(comfy.params["node_overrides"]["3.inputs.height"], 1024)
        self.assertEqual((novelai.params["width"], novelai.params["height"]), (1216, 832))

    def test_rejects_unknown_choices_and_bad_presets(self):
        def resolve(choice, presets=None):
            payload = {} if presets is None else {"size_presets": presets}
            return resolve_render_size(payload, {"size": choice}, width=1, height=1, rng=None)

        with self.assertRaisesRegex(ValueError, "random, portrait, landscape, square, custom"):
            resolve("竖")
        with self.assertRaisesRegex(ValueError, "keys must be portrait"):
            resolve("portrait", {"tall": {"width": 1024, "height": 1536}})
        with self.assertRaisesRegex(ValueError, "multiples of 8"):
            resolve("portrait", {"portrait": {"width": 1000, "height": 1001}})



class BatchResolutionMappingTest(unittest.TestCase):
    def test_batch_resolution_maps_to_render_size_choice(self):
        from tags_machine_core.batch.planner import _size_choice

        self.assertEqual(_size_choice(resolution="random_standard", width=None, height=None), "random")
        self.assertEqual(_size_choice(resolution="normal_portrait", width=None, height=None), "portrait")
        self.assertEqual(_size_choice(resolution="random_standard", width=640, height=960), "custom")
        self.assertIsNone(_size_choice(resolution="something_else", width=None, height=None))
