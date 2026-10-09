from __future__ import annotations

import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from .cache import cache_key
from .client import LLMClient, LLMError


TRANSLATE_TASK = "translate_tag"
TRANSLATE_VERSION = "1"
# DeepSeek 一次翻 100 个要半分钟以上；小批并发，首批结果能更快回到界面。
TRANSLATE_BATCH_SIZE = 40
TRANSLATE_CONCURRENCY = 4

_LEADING_WEIGHT_RE = re.compile(r"^-?\d+(?:\.\d+)?::")
_WRAPPERS = "{}[]"

_SYSTEM_PROMPT = (
    "你是 danbooru / NovelAI 提示词翻译助手。把每个英文 tag 或短语翻译成简体中文，"
    "译文要简短（通常 2 到 8 个字），按画面含义翻译，不要解释。"
    "画师名译为“画师”；角色名译为“角色:中文名”，不知道中文名就保留原名；作品名译为“作品:中文名”。"
    "自然语言句子整句翻译。"
    '只输出 JSON：{"translations": {"原文": "译文"}}，键必须和输入完全一致。'
)


class _TranslationReply(BaseModel):
    translations: dict[str, str] = Field(default_factory=dict)


def normalize_tag(tag: str) -> str:
    """查词典用的规范形式：去掉 {} [] 和 1.2::x:: 权重，统一空格、下划线和大小写。

    按逗号拆开的多词权重组（"1.2::a" / "b::"）两头也能各自去掉权重符号。
    """
    text = tag.strip()
    changed = True
    while changed and text:
        changed = False
        for pattern in (_LEADING_WEIGHT_RE,):
            stripped = pattern.sub("", text, count=1).strip()
            if stripped != text:
                text, changed = stripped, True
        if text.endswith("::"):
            text, changed = text[:-2].strip(), True
        stripped = text.strip(_WRAPPERS).strip()
        if stripped != text:
            text, changed = stripped, True
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def split_prompt_tags(prompt: str) -> list[str]:
    """粗拆：按逗号、竖线和换行切开，只给翻译和统计用；无损拆分见 P2 的分词器。"""
    return [part.strip() for part in re.split(r"[,|\n]", prompt or "") if part.strip()]


def translate_tags(client: LLMClient, tags: Iterable[str]) -> dict[str, str]:
    """返回 {原始 tag: 中文}；没翻译出来的 tag 不出现在结果里。每个 tag 单独缓存，与模型无关。"""
    originals: dict[str, list[str]] = {}
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip():
            continue
        normalized = normalize_tag(tag)
        if normalized:
            originals.setdefault(normalized, []).append(tag)
    if not originals:
        return {}

    keys = {normalized: cache_key(TRANSLATE_TASK, TRANSLATE_VERSION, normalized) for normalized in originals}
    cached = client.cache.get_many(list(keys.values()))
    resolved: dict[str, str] = {
        normalized: str(cached[key]) for normalized, key in keys.items() if key in cached
    }

    missing = [normalized for normalized in originals if normalized not in resolved]
    if missing and client.available:
        batches = [missing[start : start + TRANSLATE_BATCH_SIZE] for start in range(0, len(missing), TRANSLATE_BATCH_SIZE)]
        with ThreadPoolExecutor(max_workers=min(TRANSLATE_CONCURRENCY, len(batches))) as pool:
            for batch, reply in zip(batches, pool.map(lambda batch: _translate_batch(client, batch), batches)):
                if reply is None:
                    continue
                fresh: list[tuple[str, str]] = []
                for key, value in reply.translations.items():
                    normalized = normalize_tag(key)
                    if normalized in originals and normalized not in resolved and str(value).strip():
                        resolved[normalized] = str(value).strip()
                        fresh.append((keys[normalized], resolved[normalized]))
                if fresh:
                    client.cache.set_many(fresh, task=TRANSLATE_TASK, model=None)

    return {
        original: resolved[normalized]
        for normalized, items in originals.items()
        if normalized in resolved
        for original in items
    }


def _translate_batch(client: LLMClient, batch: list[str]) -> _TranslationReply | None:
    try:
        return client.run_json(
            task=TRANSLATE_TASK,
            version=TRANSLATE_VERSION,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
            ],
            schema=_TranslationReply,
            cache_input=batch,
            fast=True,
            use_cache=False,
        )
    except LLMError:
        return None
