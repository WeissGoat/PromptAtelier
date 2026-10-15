from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from .cache import cache_key
from .client import LLMClient, LLMError


# DeepSeek 一次处理 100 个要半分钟以上；小批并发，首批结果能更快回到界面。
TAG_BATCH_SIZE = 40
TAG_CONCURRENCY = 4


class _TagReply(BaseModel):
    results: dict[str, str] = Field(default_factory=dict)


def annotate_tags(
    client: LLMClient,
    tags: Iterable[str],
    *,
    task: str,
    version: str,
    system_prompt: str,
    normalize: Callable[[str], str],
    accept: Callable[[str], str | None] | None = None,
    fetch: bool = True,
) -> dict[str, str]:
    """对一批已规范化的 tag 逐个求一个短文本结果（译文、类别……），每个 tag 单独缓存，与模型无关。

    accept 用来校验/规范 LLM 给出的值，返回 None 表示丢弃（例如不在允许的类别里）。
    fetch=False 时只读缓存，不调用 LLM（界面刷新时用，避免阻塞）。
    返回 {规范化 tag: 结果}；没拿到结果的 tag 不出现，下次还会再问。
    """
    wanted = list(dict.fromkeys(tag for tag in tags if tag))
    if not wanted:
        return {}
    keys = {tag: cache_key(task, version, tag) for tag in wanted}
    cached = client.cache.get_many(list(keys.values()))
    resolved = {tag: str(cached[key]) for tag, key in keys.items() if key in cached}

    missing = [tag for tag in wanted if tag not in resolved]
    if missing and fetch and client.available:
        batches = [missing[start : start + TAG_BATCH_SIZE] for start in range(0, len(missing), TAG_BATCH_SIZE)]

        def run(batch: list[str]) -> _TagReply | None:
            try:
                return client.run_json(
                    task=task,
                    version=version,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
                    ],
                    schema=_TagReply,
                    cache_input=batch,
                    fast=True,
                    use_cache=False,
                )
            except LLMError:
                return None

        with ThreadPoolExecutor(max_workers=min(TAG_CONCURRENCY, len(batches))) as pool:
            for reply in pool.map(run, batches):
                if reply is None:
                    continue
                fresh: list[tuple[str, str]] = []
                for key, value in reply.results.items():
                    tag = normalize(key)
                    text = str(value).strip()
                    if accept is not None:
                        text = accept(text) or ""
                    if tag in keys and tag not in resolved and text:
                        resolved[tag] = text
                        fresh.append((keys[tag], text))
                if fresh:
                    client.cache.set_many(fresh, task=task, model=None)
    return resolved
