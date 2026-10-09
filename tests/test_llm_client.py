import json
import tempfile
from pathlib import Path
from unittest import TestCase

from pydantic import BaseModel

from tags_machine_core.config import LLMConfig
from tags_machine_core.llm import (
    LLMCache,
    LLMClient,
    LLMError,
    normalize_tag,
    resolve_api_key,
    split_prompt_tags,
    translate_tags,
)
from tags_machine_core.llm.client import extract_message_content, parse_json_content


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class _Session:
    """按调用顺序返回预设响应，并记录每次请求的模型和消息。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "body": json, "headers": headers})
        response = self.responses.pop(0)
        return response(json) if callable(response) else response


def _chat(content):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class _Reply(BaseModel):
    value: str


class LLMClientTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.cache = LLMCache(self.tmp / "cache.sqlite")

    def tearDown(self):
        self.cache.close()
        self.temp_dir.cleanup()

    def _client(self, responses, **overrides):
        config = LLMConfig(base_url="https://llm.test/v1", api_key="sk-test", **overrides)
        session = _Session(responses)
        return LLMClient(config, session=session, cache=self.cache), session

    def test_extract_content_supports_proxy_data_wrapper(self):
        self.assertEqual(extract_message_content(_chat("hi")), "hi")
        self.assertEqual(extract_message_content({"data": _chat("wrapped")}), "wrapped")
        with self.assertRaises(LLMError):
            extract_message_content({"error": "nope"})

    def test_parse_json_strips_markdown_fence_and_surrounding_text(self):
        self.assertEqual(parse_json_content('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json_content('Sure! {"a": 2} hope it helps'), {"a": 2})

    def test_run_json_falls_back_to_second_model_and_caches(self):
        client, session = self._client(
            [_Response(_chat("I can't help with that.")), _Response({"data": _chat('{"value": "ok"}')})]
        )
        kwargs = dict(
            task="t", version="1", messages=[{"role": "user", "content": "x"}], schema=_Reply, cache_input="x"
        )
        result = client.run_json(**kwargs)
        self.assertEqual(result.value, "ok")
        self.assertEqual(
            [call["body"]["model"] for call in session.calls],
            ["deepseek-4.1-flash", "gemini-3.8-flash-high"],
        )
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer sk-test")

        again = client.run_json(**kwargs)
        self.assertEqual(again.value, "ok")
        self.assertEqual(len(session.calls), 2)

    def test_run_json_raises_when_every_model_fails(self):
        client, _ = self._client([_Response({"error": "x"}, status_code=500), _Response(_chat("not json"))])
        with self.assertRaises(LLMError):
            client.run_json(task="t", version="1", messages=[], schema=_Reply, cache_input="y")

    def test_unconfigured_client_is_unavailable(self):
        client = LLMClient(LLMConfig(), session=_Session([]), cache=self.cache)
        self.assertFalse(client.available)
        self.assertEqual(translate_tags(client, ["silver hair"]), {})

    def test_api_key_file_reads_json_field(self):
        key_file = self.tmp / "auth.json"
        key_file.write_text(json.dumps({"OPENAI_API_KEY": "sk-file"}), encoding="utf-8")
        self.assertEqual(resolve_api_key(LLMConfig(api_key_file=key_file, api_key_env="")), "sk-file")
        plain = self.tmp / "key.txt"
        plain.write_text("sk-plain\n", encoding="utf-8")
        self.assertEqual(resolve_api_key(LLMConfig(api_key_file=plain, api_key_env="")), "sk-plain")


class TranslateTagsTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache = LLMCache(Path(self.temp_dir.name) / "cache.sqlite")

    def tearDown(self):
        self.cache.close()
        self.temp_dir.cleanup()

    def test_normalize_tag_strips_weights(self):
        self.assertEqual(normalize_tag("{{official art}}"), "official art")
        self.assertEqual(normalize_tag("[[akipeko]]"), "akipeko")
        self.assertEqual(normalize_tag("1.2::Silver_Hair::"), "silver hair")
        self.assertEqual(normalize_tag("-0.5::{lowres}::"), "lowres")
        self.assertEqual(normalize_tag("ame (uten cancel)"), "ame (uten cancel)")
        # 按逗号拆开的多词权重组。
        self.assertEqual(normalize_tag("1.2::pale skin"), "pale skin")
        self.assertEqual(normalize_tag("blush::"), "blush")

    def test_split_prompt_tags(self):
        self.assertEqual(
            split_prompt_tags("no text, best quality|ame(uten cancel)|[[akipeko]]\n, solo"),
            ["no text", "best quality", "ame(uten cancel)", "[[akipeko]]", "solo"],
        )

    def test_translate_tries_fast_model_first(self):
        session = _Session([_Response({"error": "blocked"}), _Response(_chat('{"translations": {"nude": "裸体"}}'))])
        client = LLMClient(LLMConfig(base_url="https://llm.test/v1", api_key="sk"), session=session, cache=self.cache)
        self.assertEqual(translate_tags(client, ["nude"]), {"nude": "裸体"})
        self.assertEqual(
            [call["body"]["model"] for call in session.calls], ["gemini-3.5-flash-lite", "deepseek-4.1-flash"]
        )

    def test_translate_shares_weighted_variants_and_caches_per_tag(self):
        def reply(body):
            tags = json.loads(body["messages"][1]["content"])
            self.assertEqual(tags, ["official art", "silver hair"])
            return _Response(_chat(json.dumps({"translations": {"official art": "官方原画", "silver hair": "银发"}})))

        session = _Session([reply])
        client = LLMClient(
            LLMConfig(base_url="https://llm.test/v1", api_key="sk"), session=session, cache=self.cache
        )
        result = translate_tags(client, ["{{official art}}", "official art", "silver hair", ""])
        self.assertEqual(
            result,
            {"{{official art}}": "官方原画", "official art": "官方原画", "silver hair": "银发"},
        )
        # 第二次全部命中缓存，不再请求。
        self.assertEqual(translate_tags(client, ["[silver hair]"]), {"[silver hair]": "银发"})
        self.assertEqual(len(session.calls), 1)

    def test_translate_skips_tags_missing_from_reply(self):
        session = _Session(
            [_Response(_chat(json.dumps({"translations": {"a": "甲"}}))), _Response(_chat('{"translations": {}}'))]
        )
        client = LLMClient(LLMConfig(base_url="https://llm.test/v1", api_key="sk"), session=session, cache=self.cache)
        self.assertEqual(translate_tags(client, ["a", "b"]), {"a": "甲"})
        # b 没翻出来，没有缓存，下次还会再问。
        self.assertEqual(translate_tags(client, ["b"]), {})
        self.assertEqual(len(session.calls), 2)
