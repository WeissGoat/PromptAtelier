"""谷歌翻译（translate.googleapis.com 的免费接口，不需要 key）。

和 AI 翻译一样按规范化后的 tag 逐个缓存在 LLM 缓存库里，任务名不同，两边的译文互不覆盖。
一次请求把多个 tag 按行拼起来翻译；返回的行数对不上时退回逐个翻译。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

import requests

from tags_machine_core.logging_config import get_logger

from .cache import LLMCache, cache_key
from .translate import normalize_tag


logger = get_logger(__name__)

GOOGLE_TRANSLATE_TASK = "translate_tag_google"
GOOGLE_TRANSLATE_VERSION = "1"
GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
_BATCH_CHARS = 1800
_CONCURRENCY = 4
_TIMEOUT = 15
_CJK_RE = re.compile(r"[぀-ヿ㐀-鿿]")


class GoogleTranslateError(RuntimeError):
    pass


def _request(text: str, session: requests.Session) -> list[str]:
    """翻译一段（可以多行），按行返回译文。"""
    response = session.post(
        GOOGLE_TRANSLATE_URL,
        params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t"},
        data={"q": text},
        timeout=_TIMEOUT,
    )
    if response.status_code != 200:
        raise GoogleTranslateError(f"Google Translate HTTP {response.status_code}")
    try:
        segments = response.json()[0] or []
    except (ValueError, IndexError, TypeError) as exc:
        raise GoogleTranslateError("Unexpected Google Translate response") from exc
    joined = "".join(str(segment[0] or "") for segment in segments if segment)
    return [line.strip() for line in joined.split("\n")]


def _batches(tags: list[str]) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    size = 0
    for tag in tags:
        if current and size + len(tag) + 1 > _BATCH_CHARS:
            batches.append(current)
            current, size = [], 0
        current.append(tag)
        size += len(tag) + 1
    if current:
        batches.append(current)
    return batches


def _translate_batch(batch: list[str], session: requests.Session) -> dict[str, str]:
    lines = _request("\n".join(batch), session)
    if len(lines) == len(batch):
        return {tag: line for tag, line in zip(batch, lines) if line}
    # 行数对不上（谷歌偶尔合并或拆开行）：逐个翻译。
    result: dict[str, str] = {}
    for tag in batch:
        single = _request(tag, session)
        if single and single[0]:
            result[tag] = single[0]
    return result


def google_translate_tags(cache: LLMCache, tags: Iterable[str]) -> dict[str, str]:
    """返回 {原始 tag: 中文}。已经是中文 / 日文的不翻；翻译失败的不出现在结果里，下次还会再请求。"""
    originals: dict[str, list[str]] = {}
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip() or _CJK_RE.search(tag):
            continue
        normalized = normalize_tag(tag)
        if normalized:
            originals.setdefault(normalized, []).append(tag)
    if not originals:
        return {}
    keys = {tag: cache_key(GOOGLE_TRANSLATE_TASK, GOOGLE_TRANSLATE_VERSION, tag) for tag in originals}
    cached = cache.get_many(list(keys.values()))
    resolved = {tag: str(cached[key]) for tag, key in keys.items() if key in cached}
    missing = [tag for tag in originals if tag not in resolved]
    if missing:
        session = requests.Session()
        batches = _batches(missing)

        def run(batch: list[str]) -> dict[str, str]:
            try:
                return _translate_batch(batch, session)
            except (requests.RequestException, GoogleTranslateError) as exc:
                logger.warning("Google Translate failed for %d tags: %s", len(batch), exc)
                return {}

        with ThreadPoolExecutor(max_workers=min(_CONCURRENCY, len(batches))) as pool:
            for fresh in pool.map(run, batches):
                if fresh:
                    resolved.update(fresh)
                    cache.set_many([(keys[tag], text) for tag, text in fresh.items()], task=GOOGLE_TRANSLATE_TASK, model=None)
    return {original: resolved[normalized] for normalized, items in originals.items() if normalized in resolved for original in items}
