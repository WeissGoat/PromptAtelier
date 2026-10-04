"""NAI5 模型支持测试 + NAI4.5 回归保护。

Part 1: NAI 4.5 回归守卫 — 锁定现有行为，证明 V5 改动不影响 V4.5
Part 2: NAI 5 新功能 — 验证 V5 专属参数和行为
Part 3: 跨模型隔离 — 验证模型匹配不会串
"""
from __future__ import annotations

import unittest

from tags_machine_core.clients import NovelAIClient
from tags_machine_core.clients.novelai import (
    DEFAULT_NOVELAI_MODEL,
    VALID_NOVELAI_MODELS,
    normalize_novelai_model,
)
from tags_machine_core.composers import ScriptComposer
from tags_machine_core.contracts import RenderRequest
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.resolved import ResolvedNode, ResolvedNodeSet
from tags_machine_core.renderers import NovelAIRenderAdapter


def _simple_bundle(prompt="1girl, standing", negative="lowres"):
    return ScriptComposer().compose_full_prompt(prompt=prompt, negative=negative)


# ---------------------------------------------------------------------------
# Part 1: NAI 4.5 回归守卫
# ---------------------------------------------------------------------------


class NAI45RegressionGuardTest(unittest.TestCase):
    """这些测试锁定 NAI 4.5 的现有行为，加入 V5 前后必须全绿。"""

    def test_nai45_models_still_in_valid_set(self):
        self.assertIn("nai-diffusion-4-5-full", VALID_NOVELAI_MODELS)
        self.assertIn("nai-diffusion-4-5-curated", VALID_NOVELAI_MODELS)

    def test_nai45_normalization_unchanged(self):
        self.assertEqual(
            normalize_novelai_model("NovelAI Diffusion V4.5 4BDE2A90"),
            "nai-diffusion-4-5-full",
        )
        self.assertEqual(
            normalize_novelai_model("NovelAI Diffusion V4.5 Curated 4BDE2A90"),
            "nai-diffusion-4-5-curated",
        )
        self.assertEqual(
            normalize_novelai_model("nai-diffusion-4-5-full"),
            "nai-diffusion-4-5-full",
        )
        self.assertEqual(
            normalize_novelai_model("nai-diffusion-4-5-curated"),
            "nai-diffusion-4-5-curated",
        )

    def test_nai45_payload_has_v4_prompt_structure(self):
        client = NovelAIClient(access_token="token", retry=1)
        request = RenderRequest(
            backend="novelai",
            prompt="1girl",
            negative_prompt="lowres",
            model="nai-diffusion-4-5-full",
        )
        payload = client.build_payload(request)

        self.assertEqual(payload["model"], "nai-diffusion-4-5-full")
        params = payload["parameters"]
        self.assertEqual(params["params_version"], 3)
        self.assertIn("v4_prompt", params)
        self.assertIn("v4_negative_prompt", params)
        self.assertEqual(params["v4_prompt"]["caption"]["base_caption"], "1girl")
        self.assertEqual(
            params["v4_negative_prompt"]["caption"]["base_caption"], "lowres"
        )

    def test_nai45_adapter_defaults_unchanged(self):
        request = NovelAIRenderAdapter().build_request(
            _simple_bundle(),
            seed=100,
            model="nai-diffusion-4-5-full",
        )
        p = request.params

        # V4.5 用旧式 ucPreset(int) / qualityToggle(bool)
        self.assertEqual(p["ucPreset"], 3)
        self.assertFalse(p["qualityToggle"])
        self.assertNotIn("ucPresetId", p)
        self.assertNotIn("qualityPresetId", p)

        # V4.5 默认 scheduler 是 native，不是 karras
        self.assertEqual(p["noise_schedule"], "native")

        # V4.5 没有 straight_alpha
        self.assertNotIn("straight_alpha", p)

        # sm / sm_dyn 存在
        self.assertIn("sm", p)
        self.assertIn("sm_dyn", p)

        # v4_prompt 默认 use_coords=False
        self.assertFalse(p["v4_prompt"]["use_coords"])

    def test_nai45_character_prompts_still_work(self):
        homura = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"], "hair": ["black hair"]},
        )
        resolved = ResolvedNodeSet(
            [ResolvedNode(role="character", ref="homura", index=0, node=homura)]
        )
        bundle = ScriptComposer().compose_full_prompt(
            prompt="akemi homura, black hair, 1girl"
        )

        request = NovelAIRenderAdapter().build_request(
            bundle,
            seed=123,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        caption = request.params["v4_prompt"]["caption"]
        self.assertEqual(len(caption["char_captions"]), 1)
        self.assertIn("akemi homura", caption["char_captions"][0]["char_caption"])
        self.assertEqual(request.meta["character_prompts"]["mode"], "auto")

    def test_nai45_character_prompts_max_6(self):
        """V4.5 最多 6 个角色。"""
        characters = []
        for i in range(8):
            char = NodeDocument(
                kind="character",
                id=f"char_{i}",
                tags={"character": [f"character_{i}"]},
            )
            characters.append(
                ResolvedNode(role="character", ref=f"char_{i}", index=i, node=char)
            )
        resolved = ResolvedNodeSet(characters)
        prompt_parts = ", ".join(f"character_{i}" for i in range(8))
        bundle = ScriptComposer().compose_full_prompt(prompt=prompt_parts)

        request = NovelAIRenderAdapter().build_request(
            bundle,
            seed=1,
            model="nai-diffusion-4-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        char_count = len(request.params["v4_prompt"]["caption"]["char_captions"])
        self.assertLessEqual(char_count, 6)

    def test_nai45_client_payload_complete_structure(self):
        """端到端验证: adapter -> client -> payload 的完整 V4.5 结构。"""
        bundle = _simple_bundle(prompt="1girl, standing", negative="bad anatomy")
        render_request = NovelAIRenderAdapter().build_request(
            bundle, seed=42, model="nai-diffusion-4-5-full"
        )
        client = NovelAIClient(access_token="token", retry=1)
        payload = client.build_payload(render_request)

        self.assertEqual(payload["model"], "nai-diffusion-4-5-full")
        self.assertEqual(payload["action"], "generate")
        params = payload["parameters"]
        self.assertIn("v4_prompt", params)
        self.assertIn("v4_negative_prompt", params)
        self.assertEqual(params["uc"], render_request.negative_prompt)
        # V4.5 不应该有 V5 专属字段
        self.assertNotIn("straight_alpha", params)
        self.assertNotIn("ucPresetId", params)
        self.assertNotIn("qualityPresetId", params)


# ---------------------------------------------------------------------------
# Part 2: NAI 5 新功能
# ---------------------------------------------------------------------------


class NAI5ModelSupportTest(unittest.TestCase):
    def test_nai5_models_in_valid_set(self):
        self.assertIn("nai-diffusion-5-full", VALID_NOVELAI_MODELS)
        self.assertIn("nai-diffusion-5-curated", VALID_NOVELAI_MODELS)

    def test_nai5_exact_normalization(self):
        self.assertEqual(
            normalize_novelai_model("nai-diffusion-5-full"),
            "nai-diffusion-5-full",
        )
        self.assertEqual(
            normalize_novelai_model("nai-diffusion-5-curated"),
            "nai-diffusion-5-curated",
        )

    def test_nai5_fuzzy_normalization(self):
        self.assertEqual(
            normalize_novelai_model("NovelAI Diffusion V5 Full"),
            "nai-diffusion-5-full",
        )
        self.assertEqual(
            normalize_novelai_model("NovelAI Diffusion V5 Curated"),
            "nai-diffusion-5-curated",
        )
        self.assertEqual(normalize_novelai_model("v5"), "nai-diffusion-5-full")
        self.assertEqual(
            normalize_novelai_model("NovelAI V5"), "nai-diffusion-5-full"
        )

    def test_nai5_normalization_does_not_collide_with_v45(self):
        """关键隔离测试: V4.5 模型名不会被误匹配为 V5。"""
        self.assertEqual(
            normalize_novelai_model("nai-diffusion-4-5-full"),
            "nai-diffusion-4-5-full",
        )
        self.assertEqual(
            normalize_novelai_model("v4.5"),
            "nai-diffusion-4-5-full",
        )
        self.assertEqual(
            normalize_novelai_model("NovelAI Diffusion V4.5"),
            "nai-diffusion-4-5-full",
        )
        self.assertEqual(
            normalize_novelai_model("NovelAI Diffusion V4.5 Curated"),
            "nai-diffusion-4-5-curated",
        )

    def test_nai5_adapter_forces_karras_noise_schedule(self):
        request = NovelAIRenderAdapter().build_request(
            _simple_bundle(),
            seed=1,
            model="nai-diffusion-5-full",
        )
        self.assertEqual(request.params["noise_schedule"], "karras")

    def test_nai5_curated_adapter_forces_karras(self):
        request = NovelAIRenderAdapter().build_request(
            _simple_bundle(),
            seed=1,
            model="nai-diffusion-5-curated",
        )
        self.assertEqual(request.params["noise_schedule"], "karras")

    def test_nai5_adapter_uses_preset_ids_not_legacy_toggles(self):
        request = NovelAIRenderAdapter().build_request(
            _simple_bundle(),
            seed=1,
            model="nai-diffusion-5-full",
        )
        p = request.params

        # V5 用字符串 preset ID
        self.assertEqual(p["ucPresetId"], "heavy")
        self.assertEqual(p["qualityPresetId"], "standard")

        # 旧的 ucPreset / qualityToggle 不应存在
        self.assertNotIn("ucPreset", p)
        self.assertNotIn("qualityToggle", p)

    def test_nai5_adapter_includes_straight_alpha(self):
        request = NovelAIRenderAdapter().build_request(
            _simple_bundle(),
            seed=1,
            model="nai-diffusion-5-full",
        )
        self.assertTrue(request.params["straight_alpha"])

    def test_nai5_adapter_includes_normalize_reference_strength(self):
        request = NovelAIRenderAdapter().build_request(
            _simple_bundle(),
            seed=1,
            model="nai-diffusion-5-full",
        )
        self.assertTrue(request.params["normalize_reference_strength_multiple"])

    def test_nai5_adapter_includes_inpaint_strength(self):
        request = NovelAIRenderAdapter().build_request(
            _simple_bundle(),
            seed=1,
            model="nai-diffusion-5-full",
        )
        self.assertEqual(request.params["inpaintImg2ImgStrength"], 1.0)

    def test_nai5_adapter_has_v4_prompt_structure(self):
        request = NovelAIRenderAdapter().build_request(
            _simple_bundle(),
            seed=1,
            model="nai-diffusion-5-full",
        )
        p = request.params
        self.assertIn("v4_prompt", p)
        self.assertIn("v4_negative_prompt", p)
        self.assertIn("base_caption", p["v4_prompt"]["caption"])
        self.assertIn("char_captions", p["v4_prompt"]["caption"])

    def test_nai5_supports_character_prompts(self):
        homura = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"]},
        )
        resolved = ResolvedNodeSet(
            [ResolvedNode(role="character", ref="homura", index=0, node=homura)]
        )
        bundle = ScriptComposer().compose_full_prompt(prompt="akemi homura, 1girl")

        request = NovelAIRenderAdapter().build_request(
            bundle,
            seed=1,
            model="nai-diffusion-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        caption = request.params["v4_prompt"]["caption"]
        self.assertEqual(len(caption["char_captions"]), 1)
        self.assertIn("akemi homura", caption["char_captions"][0]["char_caption"])

    def test_nai5_character_prompts_max_32(self):
        """V5 最多 32 个角色（V4 只支持 6 个）。"""
        characters = []
        for i in range(10):
            char = NodeDocument(
                kind="character",
                id=f"char_{i}",
                tags={"character": [f"character_{i}"]},
            )
            characters.append(
                ResolvedNode(role="character", ref=f"char_{i}", index=i, node=char)
            )
        resolved = ResolvedNodeSet(characters)
        prompt_parts = ", ".join(f"character_{i}" for i in range(10))
        bundle = ScriptComposer().compose_full_prompt(prompt=prompt_parts)

        request = NovelAIRenderAdapter().build_request(
            bundle,
            seed=1,
            model="nai-diffusion-5-full",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        char_count = len(request.params["v4_prompt"]["caption"]["char_captions"])
        # V5 应该能容纳全部 10 个角色（上限 32）
        self.assertEqual(char_count, 10)

    def test_nai5_client_payload_has_v4_prompt(self):
        """端到端验证: adapter -> client -> payload 的 V5 结构。"""
        bundle = _simple_bundle()
        render_request = NovelAIRenderAdapter().build_request(
            bundle, seed=42, model="nai-diffusion-5-full"
        )
        client = NovelAIClient(access_token="token", retry=1)
        payload = client.build_payload(render_request)

        self.assertEqual(payload["model"], "nai-diffusion-5-full")
        params = payload["parameters"]
        self.assertIn("v4_prompt", params)
        self.assertIn("v4_negative_prompt", params)
        self.assertEqual(
            params["v4_prompt"]["caption"]["base_caption"],
            render_request.prompt,
        )

    def test_nai5_use_coords_default_false(self):
        request = NovelAIRenderAdapter().build_request(
            _simple_bundle(),
            seed=1,
            model="nai-diffusion-5-full",
        )
        self.assertFalse(request.params["use_coords"])
        self.assertFalse(request.params["v4_prompt"]["use_coords"])

    def test_nai5_use_coords_can_be_enabled(self):
        request = NovelAIRenderAdapter().build_request(
            _simple_bundle(),
            seed=1,
            model="nai-diffusion-5-full",
            params={"use_coords": True},
        )
        self.assertTrue(request.params["use_coords"])
        self.assertTrue(request.params["v4_prompt"]["use_coords"])


# ---------------------------------------------------------------------------
# Part 3: 跨模型隔离
# ---------------------------------------------------------------------------


class CrossModelIsolationTest(unittest.TestCase):
    def test_default_model_unchanged(self):
        self.assertEqual(DEFAULT_NOVELAI_MODEL, "nai-diffusion-4-5-full")

    def test_v3_normalization_unaffected(self):
        self.assertEqual(
            normalize_novelai_model("NovelAI Diffusion V3"),
            "nai-diffusion-3",
        )
        self.assertEqual(
            normalize_novelai_model("nai-diffusion-3"),
            "nai-diffusion-3",
        )

    def test_v3_does_not_support_character_prompts(self):
        homura = NodeDocument(
            kind="character",
            id="homura",
            tags={"character": ["akemi homura"]},
        )
        resolved = ResolvedNodeSet(
            [ResolvedNode(role="character", ref="homura", index=0, node=homura)]
        )
        bundle = ScriptComposer().compose_full_prompt(prompt="akemi homura, 1girl")

        request = NovelAIRenderAdapter().build_request(
            bundle,
            seed=1,
            model="nai-diffusion-3",
            params={"character_prompts": {"mode": "auto"}},
            resolved_nodes=resolved,
        )

        self.assertEqual(
            request.meta["character_prompts"]["status"], "unsupported_model"
        )

    def test_furry_normalization_unaffected(self):
        self.assertEqual(
            normalize_novelai_model("NovelAI Diffusion Furry V3"),
            "nai-diffusion-furry-3",
        )

    def test_none_model_defaults_to_v45(self):
        self.assertEqual(normalize_novelai_model(None), "nai-diffusion-4-5-full")
        self.assertEqual(normalize_novelai_model(""), "nai-diffusion-4-5-full")


if __name__ == "__main__":
    unittest.main()
