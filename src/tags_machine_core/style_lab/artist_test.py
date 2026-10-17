"""用导出后的 artist 出图测试。artist 按名字从 design/画风 读取，走和日常出图完全一样的链路。

- 回归对照：挑同组的几张原图，去掉原图里的画风 token 留下内容，用原图的种子、尺寸、角色提示词出图，再和原图对照。
  配方里丢弃的词默认留在内容里（原图里有它们，去掉了就比的不是同一张图），也可以选一起去掉；
- 泛化矩阵：提示词库的角色 × 动作，固定一个种子，看画风换了内容还稳不稳。
"""

from __future__ import annotations

import random
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .classify import STYLE_CATEGORIES, token_category
from .metadata import ImageRecord
from .recipe import Recipe, RecipeToken
from .regenerate import SizeMode
from .tokens import SEPARATORS, TokenList, inner_tags, serialize, tokenize


MAX_REGRESSION_IMAGES = 12
MAX_MATRIX_SIDE = 4
DEFAULT_REGRESSION_COUNT = 4
DEFAULT_MATRIX_SIZE = (832, 1216)
_SKIP_FLAGS = {"no_metadata", "inpaint", "img2img"}


class ArtistTestSettings(BaseModel):
    kind: Literal["regression", "matrix"]
    artist: str
    image_ids: list[str] = Field(default_factory=list, max_length=MAX_REGRESSION_IMAGES)
    characters: list[str] = Field(default_factory=list, max_length=MAX_MATRIX_SIDE)
    actions: list[str] = Field(default_factory=list, max_length=MAX_MATRIX_SIDE)
    seed_mode: Literal["source", "random", "fixed"] = "source"
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    width: int | None = Field(default=None, ge=64, le=2048)
    height: int | None = Field(default=None, ge=64, le=2048)
    # 没写时按旧规则：给了宽高就是 custom，否则回归用原图尺寸、矩阵用默认竖图。
    size_mode: SizeMode | None = None
    # 回归对照时配方里丢弃的词：keep 留在内容里（和原图对齐），strip 一起去掉（只看导出的画风）。
    dropped: Literal["keep", "strip"] = "keep"

    @model_validator(mode="after")
    def _check(self) -> "ArtistTestSettings":
        if self.seed_mode == "fixed" and self.seed is None:
            raise ValueError("seed_mode=fixed requires seed")
        if (self.width is None) != (self.height is None):
            raise ValueError("width and height must be given together")
        if self.size_mode is None:
            self.size_mode = "custom" if self.width else "source"
        if self.size_mode == "custom" and self.width is None:
            raise ValueError("size_mode=custom requires width and height")
        if self.kind == "matrix" and not (self.characters or self.actions):
            raise ValueError("matrix needs at least one character or action")
        return self


def _norm(text: str) -> str:
    return " ".join(text.replace("_", " ").lower().split())


def _tag_norms(zones: tuple[list[RecipeToken], ...]) -> set[str]:
    """配方的块按 tag 拆开后的规范化文本（块是整段文字，原图提示词是按 tag 比的）。"""
    return {_norm(tag.text) for zone in zones for token in zone for tag in tokenize(token.text).tokens}


def style_zones(recipe: Recipe, *, strip_dropped: bool = True) -> tuple[list[RecipeToken], ...]:
    return (recipe.prefix, recipe.suffix, recipe.dropped) if strip_dropped else (recipe.prefix, recipe.suffix)


def style_blocks(recipe: Recipe, *, strip_dropped: bool = True) -> list[str]:
    """配方里画风（和要去掉的丢弃）的整块文字：原图里原样出现时整段去掉，权重语法不会被拆坏。"""
    zones = style_zones(recipe, strip_dropped=strip_dropped)
    return [token.text.strip() for zone in zones for token in zone if token.text.strip()]


def style_norms(recipe: Recipe, *, strip_dropped: bool = True) -> set[str]:
    """配方里画风（和要去掉的丢弃）的 tag：回归对照时从原图提示词里去掉它们。"""
    return _tag_norms(style_zones(recipe, strip_dropped=strip_dropped))


def subject_norms(recipe: Recipe, *, keep_dropped: bool = False) -> set[str]:
    """配方里手动留在主体（和留在内容里的丢弃）的 tag：分类说是风格也不去掉，以用户的划分为准。"""
    return _tag_norms((recipe.subject, recipe.dropped) if keep_dropped else (recipe.subject,))


_SEPARATOR_CLASS = r"[,，|\n]"


def _cut_blocks(prompt: str, blocks: list[str]) -> tuple[str, list[str]]:
    """整块去掉：块前后必须是分隔符或首尾，"girl" 不会切掉 "1girl" 的一部分。长的先切。"""
    removed: list[str] = []
    for block in sorted(set(blocks), key=len, reverse=True):
        pattern = re.compile(rf"(^|{_SEPARATOR_CLASS})\s*{re.escape(block)}\s*(?={_SEPARATOR_CLASS}|$)")
        prompt, count = pattern.subn(lambda match: match.group(1), prompt)
        if count:
            removed.append(block)
    return prompt, removed


def strip_style(
    prompt: str,
    norms: set[str],
    categories: dict[str, str],
    keep: set[str] | None = None,
    *,
    blocks: list[str] | None = None,
) -> tuple[str, list[str]]:
    """原图提示词去掉画风：配方里的画风块和 tag，加上分类为画师/风格/质量/元信息的 tag。返回（内容, 去掉的）。

    去掉以后只剩权重符号、没有内容的碎片（比如被拆开的权重组留下的 "::"）也一起去掉。
    """
    prompt, removed = _cut_blocks(prompt, blocks or [])
    kept = []
    keep = keep or set()
    for token in tokenize(prompt).tokens:
        norm = _norm(token.text)
        if not inner_tags(token.text):
            removed.append(token.text)
        elif norm in norms or (norm not in keep and token_category(token.text, categories) in STYLE_CATEGORIES):
            removed.append(token.text)
        else:
            kept.append(token)
    # 中间整块切掉后，后一个 tag 前会有两个逗号：只留最后一个分隔符。
    for token in kept:
        marks = [index for index, char in enumerate(token.sep) if char in SEPARATORS]
        if len(marks) > 1:
            token.sep = token.sep[marks[-1]:]
    return serialize(TokenList(tokens=kept)).strip(" ,"), removed


def pick_regression_images(
    images: list[ImageRecord], candidate_ids: list[str] | None, *, first_id: str | None, limit: int = DEFAULT_REGRESSION_COUNT
) -> list[ImageRecord]:
    """默认挑法：同组里每个投稿一张能复现的原图，配方原图排第一，其余按投稿日期从新到旧。"""
    allowed = set(candidate_ids) if candidate_ids else None
    usable = [
        image
        for image in images
        if image.has_metadata and not (_SKIP_FLAGS & set(image.flags)) and (allowed is None or image.id in allowed)
    ]
    usable.sort(key=lambda image: (image.id != first_id, -_post_order(image)))
    picked: list[ImageRecord] = []
    seen_posts: set[str] = set()
    for image in usable:
        post_key = image.post.post_id if image.post and image.post.post_id else image.id
        if post_key in seen_posts:
            continue
        seen_posts.add(post_key)
        picked.append(image)
        if len(picked) >= limit:
            break
    return picked


def _post_order(image: ImageRecord) -> float:
    date = image.post.date if image.post and image.post.date else ""
    return float(date.replace("-", "") or 0)


def plan_seed(settings: ArtistTestSettings, source_seed: int | None, shared: int) -> int:
    if settings.seed_mode == "fixed" and settings.seed is not None:
        return settings.seed
    if settings.seed_mode == "source" and source_seed is not None:
        return int(source_seed)
    return shared


def shared_random_seed() -> int:
    return random.randint(0, 2**32 - 1)


def regression_payload(
    settings: ArtistTestSettings, record: ImageRecord, subject: str, seed: int, size: tuple[int, int] | None = None
) -> dict[str, Any]:
    params: dict[str, Any] = {"size": "custom", "n_samples": 1}
    # 角色提示词照搬原图（全部条目），不再按计数自动补男角色，和原图一致。
    captions = [
        {"positive": caption.positive, "negative": caption.negative}
        for caption in record.char_captions
        if caption.positive.strip()
    ]
    if captions:
        params["character_prompts"] = {"mode": "explicit", "captions": captions, "add_male_caption": False}
    return {
        "compose": {"prompt": subject, "negative": ""},
        "render": {
            "backend": "novelai",
            "artist": settings.artist,
            "width": size[0] if size else settings.width or record.generation_size()[0] or 1024,
            "height": size[1] if size else settings.height or record.generation_size()[1] or 1024,
            "seed": seed,
            "params": params,
        },
    }


def matrix_cells(settings: ArtistTestSettings) -> list[tuple[str | None, str | None]]:
    characters: list[str | None] = list(settings.characters) or [None]
    actions: list[str | None] = list(settings.actions) or [None]
    return [(character, action) for character in characters for action in actions]


def matrix_payload(
    settings: ArtistTestSettings,
    character: str | None,
    action: str | None,
    seed: int,
    size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    nodes = {}
    if character:
        nodes["character"] = character
    if action:
        nodes["action"] = action
    width, height = size or ((settings.width, settings.height) if settings.width and settings.height else DEFAULT_MATRIX_SIZE)
    return {
        "compose": {"nodes": nodes},
        "render": {
            "backend": "novelai",
            "artist": settings.artist,
            "width": width,
            "height": height,
            "seed": seed,
            "params": {"size": "custom", "n_samples": 1},
        },
    }
