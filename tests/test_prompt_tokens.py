import json
from pathlib import Path
from unittest import TestCase

from tags_machine_core.style_lab.tokens import Token, TokenList, inner_tags, serialize, tokenize


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "prompt_tokens.json").read_text(encoding="utf-8"))
CORPUS_PROMPTS = [
    "eye-level, from flont, face focus, looking up,Dutch angle,upper body, 1girl, solo, 1.0::loli::, 1.0::pale skin, ::, "
    "artist:[[takeda hinata, kawauchi_(kaz7ry), rurudo, [sonao, sabana], [(houkisei:1.0, inugami kira:0.5)]"
    "[nanase miori:1.0, sakana (flame sakana):0.4], [rubi-sama, tsukimi(xiaohuasan)]]], very aesthetic, masterpiece, no text",
    "{{official art}}, {{thin lines}}, shirabi,no text, best quality, very aesthetic, absurdres|ame(uten cancel)|"
    "[shinomu(cinomoon)], [[akipeko]], year 2023\n,\nbeautiful detailed eyes, 1girl",
]


class PromptTokensTest(TestCase):
    def test_tokenize_fixtures_and_round_trip(self):
        for case in FIXTURES["tokenize"]:
            with self.subTest(case["name"]):
                result = tokenize(case["input"])
                self.assertEqual(result.texts(), case["tokens"])
                self.assertEqual(serialize(result), case["input"])

    def test_inner_tags_fixtures(self):
        for case in FIXTURES["inner_tags"]:
            with self.subTest(case["input"]):
                self.assertEqual(inner_tags(case["input"]), case["tags"])

    def test_serialize_fixtures(self):
        for case in FIXTURES["serialize"]:
            with self.subTest(case["name"]):
                tokens = TokenList(
                    leading=case["leading"],
                    tokens=[Token(text=item["text"], sep=item["sep"]) for item in case["tokens"]],
                    trailing=case["trailing"],
                )
                self.assertEqual(serialize(tokens), case["output"])

    def test_real_prompts_round_trip(self):
        for prompt in CORPUS_PROMPTS:
            result = tokenize(prompt)
            self.assertEqual(serialize(result), prompt)
        artist_mix = tokenize(CORPUS_PROMPTS[0]).texts()
        self.assertTrue(any(text.startswith("artist:[[takeda hinata") and text.endswith("]]]") for text in artist_mix))
