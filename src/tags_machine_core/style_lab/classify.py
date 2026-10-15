"""tag 分类：判断一个 tag 属于画风（画师、风格、质量、元信息）还是主体内容。

先用规则处理确定的情况（计数词、质量词、年份等），其余交给 LLM，每个 tag 单独缓存。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from tags_machine_core.llm import LLMClient
from tags_machine_core.llm.tag_tasks import annotate_tags

from .tokens import inner_tags


CLASSIFY_TASK = "classify_tag"
CLASSIFY_VERSION = "1"

STYLE_CATEGORIES = ("artist", "style", "quality", "meta")
SUBJECT_CATEGORIES = (
    "count",
    "character",
    "appearance",
    "clothing",
    "action",
    "expression",
    "scene",
    "camera",
    "nsfw",
)
CATEGORIES = (*STYLE_CATEGORIES, *SUBJECT_CATEGORIES, "other")

_COUNT_RE = re.compile(r"^(\d+\+?\s*(girl|boy|other)s?|solo|solo focus|multiple (girls|boys)|no humans|\d+ (girl|boy)s?)$")
_YEAR_RE = re.compile(r"^(year \d{4}|\d{4}s \(style\)|(early|mid|late|newest|oldest|recent))$")
_QUALITY_WORDS = {
    "masterpiece",
    "best quality",
    "high quality",
    "amazing quality",
    "good quality",
    "normal quality",
    "very aesthetic",
    "aesthetic",
    "displeasing",
    "very displeasing",
    "absurdres",
    "highres",
    "incredibly absurdres",
    "lowres",
    "ultra detailed",
    "extremely detailed",
    "very detailed",
    "highly detailed",
    "detailed",
    "very awa",
    "worst quality",
    "bad quality",
    "low quality",
}
_META_WORDS = {"no text", "official art", "commentary request", "highres", "translated"}

_SYSTEM_PROMPT = (
    "你在给 NovelAI / danbooru 提示词里的 tag 分类，用于区分“画风”和“画面内容”。每个 tag 只能选一个类别：\n"
    "artist：画师名（含 artist: 前缀或画师的罗马字/日文名）；"
    "style：画风、媒介、上色和渲染方式（如 flat color, anime coloring, watercolor, sketch, cel shading, official art, "
    "thick lines, soft lighting 这类画面质感）；"
    "quality：质量词（masterpiece, best quality, absurdres, very aesthetic 等）；"
    "meta：年份、no text、版本这类元信息；"
    "count：人数（1girl, solo, 2boys）；character：角色名或作品名；appearance：外貌（发型、发色、瞳色、体型、肤色）；"
    "clothing：服装和饰品；action：动作、姿势、互动；expression：表情和情绪；scene：背景、场景、道具、天气；"
    "camera：镜头和构图（from above, close-up, upper body, dutch angle）；nsfw：性相关内容；other：都不是。\n"
    '只输出 JSON：{"results": {"原文": "类别"}}，键必须和输入完全一致，类别只能用上面的英文名。'
)


def rule_category(tag: str) -> str | None:
    """规则能确定的类别；tag 已规范化。"""
    if _COUNT_RE.match(tag):
        return "count"
    if tag in _QUALITY_WORDS or tag.endswith(" quality") or "resolution" in tag:
        return "quality"
    if tag in _META_WORDS or _YEAR_RE.match(tag):
        return "meta"
    return None


def _accept(value: str) -> str | None:
    value = value.strip().lower()
    return value if value in CATEGORIES else None


def classify_tags(client: LLMClient | None, tags: Iterable[str], *, fetch: bool = True) -> dict[str, str]:
    """返回 {规范化 tag: 类别}。LLM 不可用时只返回规则能判断的部分；fetch=False 只读缓存。"""
    result: dict[str, str] = {}
    unknown: list[str] = []
    for tag in dict.fromkeys(tags):
        if not tag:
            continue
        category = rule_category(tag)
        if category:
            result[tag] = category
        else:
            unknown.append(tag)
    if unknown and client is not None:
        result.update(
            annotate_tags(
                client,
                unknown,
                task=CLASSIFY_TASK,
                version=CLASSIFY_VERSION,
                system_prompt=_SYSTEM_PROMPT,
                normalize=_normalize,
                accept=_accept,
                fetch=fetch,
            )
        )
    return result


def token_category(token_text: str, categories: dict[str, str]) -> str | None:
    """一个 token（可能是权重组/括号组）的类别：artist: 前缀算画师；组里有画师算画师，否则取多数。"""
    if token_text.lstrip("{[(-0123456789.:").lower().startswith("artist:"):
        return "artist"
    tags = inner_tags(token_text)
    found = [categories[tag] for tag in tags if tag in categories]
    if not found:
        return None
    if "artist" in found:
        return "artist"
    return max(set(found), key=found.count)


def _normalize(tag: str) -> str:
    tags = inner_tags(tag)
    return tags[0] if tags else ""
