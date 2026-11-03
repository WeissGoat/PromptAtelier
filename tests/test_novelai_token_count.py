from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from tags_machine_core import prompt_tokens as pt
from tags_machine_core.compose_contracts import parse_contract
from tags_machine_core.compose_contracts.profiles import load_format_profiles
from tags_machine_core.compose_contracts.validators import TokenLength, frame_token_usage

SAMPLE = "1girl, solo, {smile}, 1.2::blue hair::, [looking at viewer], masterpiece"


class _Offline:
    """没有缓存、禁止下载：分词器不可用，走估算。"""

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TM_TOKENIZER_DIR": self.temp.name, "TM_TOKENIZER_DOWNLOAD": "0"})
        self.env.start()
        self.loaded = mock.patch.dict(pt._loaded, clear=True)
        self.loaded.start()
        return self

    def __exit__(self, *exc):
        self.loaded.stop()
        self.env.stop()
        self.temp.cleanup()


def _exact_available(kind: str) -> bool:
    return pt.count_tokens("a", kind, allow_download=False).exact


class NovelAISpecTest(unittest.TestCase):
    def test_model_table_matches_site(self):
        self.assertEqual(pt.novelai_token_spec("nai-diffusion-5-full"), ("qwen", 1471, True))
        self.assertEqual(pt.novelai_token_spec("nai-diffusion-5-full-medium"), ("qwen", 1471, True))
        self.assertEqual(pt.novelai_token_spec("nai-diffusion-5-curated"), ("qwen", 703, True))
        self.assertEqual(pt.novelai_token_spec("nai-diffusion-4-5-full"), ("t5", 512, True))
        self.assertEqual(pt.novelai_token_spec("nai-diffusion-4-curated-preview"), ("t5", 512, True))
        self.assertEqual(pt.novelai_token_spec("nai-diffusion-3"), ("clip", 225, False))
        self.assertEqual(pt.novelai_token_spec("nai-diffusion-furry-3"), ("clip", 225, False))

    def test_preprocess_follows_site_rules(self):
        self.assertEqual(pt.preprocess("{Smile}, [Sad] &amp;amp; x", "clip"), "smile , sad & x")
        self.assertEqual(pt.preprocess("{smile}, 1.2::blue hair::, -0.5::sad::", "t5"), "smile, blue hair, sad")
        self.assertEqual(pt.preprocess("1.2::{x}::", "qwen"), "1.2::{x}::")

    def test_profiles_carry_site_limits(self):
        profiles = load_format_profiles()
        expected = {
            "nai-v3": ("clip", 225, False),
            "nai-v4": ("t5", 512, True),
            "nai-v4.5": ("t5", 512, True),
            "nai-v5": ("qwen", 1471, True),
            "nai-v5-curated": ("qwen", 703, True),
        }
        for profile_id, (tokenizer, limit, shared) in expected.items():
            length = profiles[profile_id].length
            self.assertEqual((length.tokenizer, length.max_tokens, length.shared_with_characters), (tokenizer, limit, shared), profile_id)
            self.assertEqual(pt.novelai_token_spec(profiles[profile_id].models[0]), (tokenizer, limit, shared), profile_id)


class CountTest(unittest.TestCase):
    def test_falls_back_to_estimate_without_tokenizer(self):
        with _Offline():
            count = pt.count_tokens(SAMPLE, "t5")
        self.assertFalse(count.exact)
        self.assertGreater(count.count, 10)

    def test_exact_counts_match_site(self):
        # 数值来自 NovelAI 官网词表（novelai.net/tokenizer/compressed/*.def）按官网预处理后的结果。
        for kind, expected in (("clip", 20), ("t5", 16), ("qwen", 24)):
            if not _exact_available(kind):
                self.skipTest(f"本地没有 {kind} 分词器缓存")
            self.assertEqual(pt.count_tokens(SAMPLE, kind).count, expected, kind)
        self.assertEqual(pt.count_tokens("", "t5").count, 1)

    def test_shared_limit_sums_characters(self):
        with mock.patch.object(pt, "count_tokens", side_effect=lambda text, kind, **_: pt.TokenCount(len(text), True, kind)):
            usage = pt.prompt_token_usage("aaaa", ["bb", "ccc"], tokenizer="t5", limit=8, shared=True)
            self.assertEqual((usage["base"], usage["characters"], usage["total"], usage["over"]), (4, [2, 3], 9, True))
            usage = pt.prompt_token_usage("aaaa", ["bb"], tokenizer="clip", limit=4, shared=False)
            self.assertEqual((usage["total"], usage["over"]), (4, False))

    def test_render_request_usage_reads_final_prompt_and_captions(self):
        request = {
            "backend": "novelai",
            "model": "nai-diffusion-4-5-full",
            "prompt": "artist:x, 1girl",
            "params": {"v4_prompt": {"caption": {"char_captions": [{"char_caption": "girl, red hair"}]}}},
        }
        with mock.patch.object(pt, "count_tokens", side_effect=lambda text, kind, **_: pt.TokenCount(len(text.split(",")), True, kind)):
            usage = pt.render_request_token_usage(request)
        self.assertEqual(usage["tokenizer"], "t5")
        self.assertEqual(usage["limit"], 512)
        self.assertEqual(usage["characters"], [2])
        self.assertEqual(usage["total"], 4)
        self.assertIsNone(pt.render_request_token_usage({"backend": "comfyui"}))


CONTRACT = """---
schema: tags-machine.compose-contract/v1
id: demo
status: done
target_format: nai-v4.5
nodes:
  characters:
    c1: { ref: "a" }
    c2: { ref: "b" }
  action_group: { ref: stn_1 }
---

## f01 x
source: custom
characters: c1, c2

```positive
2girls, hug
```

```positive c2
girl, red hair
```
"""


class ValidatorTest(unittest.TestCase):
    def setUp(self):
        self.profile = load_format_profiles()["nai-v4.5"]
        self.frame = parse_contract(CONTRACT).frames[0]

    def _fake(self, exact: bool):
        return mock.patch.object(pt, "count_tokens", side_effect=lambda text, kind, **_: pt.TokenCount(300, exact, kind))

    def test_frame_usage_includes_character_blocks(self):
        with self._fake(True):
            usage = frame_token_usage(self.frame, self.profile)
        self.assertEqual(usage["total"], 600)
        self.assertEqual(usage["blocks"], {"positive": 300, "positive c2": 300})
        self.assertTrue(usage["over"])

    def test_exact_overflow_is_error_estimate_is_warning(self):
        with self._fake(True):
            issues = TokenLength().validate_frame(self.frame, self.profile, None)
        self.assertEqual([issue.severity for issue in issues], ["error"])
        self.assertIn("合计 600 token", issues[0].message)
        with self._fake(False):
            issues = TokenLength().validate_frame(self.frame, self.profile, None)
        self.assertEqual([issue.severity for issue in issues], ["warn"])
        self.assertIn("估算", issues[0].message)

    def test_sdxl_overflow_only_warns_and_ignores_paren_weights(self):
        profile = load_format_profiles()["sdxl-danbooru"]
        frame = parse_contract(CONTRACT.replace("2girls, hug", "(night:1.2), hug")).frames[0]
        seen = []
        with mock.patch.object(pt, "count_tokens", side_effect=lambda text, kind, **_: seen.append(text) or pt.TokenCount(999, True, kind)):
            issues = TokenLength().validate_frame(frame, profile, None)
        self.assertEqual(seen[0], "night, hug")
        self.assertEqual([issue.severity for issue in issues], ["warn"])


if __name__ == "__main__":
    unittest.main()
