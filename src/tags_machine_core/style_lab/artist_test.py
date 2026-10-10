"""用导出后的 artist 出图测试。artist 按名字从 design/画风 读取，走和日常出图完全一样的链路。

- 回归对照：挑同组的几张原图，去掉原图里的画风 token 留下内容，用原图的种子、尺寸、角色提示词出图，再和原图对照；
- 泛化矩阵：提示词库的角色 × 动作，固定一个种子，看画风换了内容还稳不稳。
"""

from __future__ import annotations

import random
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .classify import STYLE_CATEGORIES, token_category
from .metadata import ImageRecord
from .recipe import Recipe
from .tokens import TokenList, serialize, tokenize


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

    @model_validator(mode="after")
    def _check(self) -> "ArtistTestSettings":
        if self.seed_mode == "fixed" and self.seed is None:
            raise ValueError("seed_mode=fixed requires seed")
        if (self.width is None) != (self.height is None):
            raise ValueError("width and height must be given together")
        if self.kind == "matrix" and not (self.characters or self.actions):
            raise ValueError("matrix needs at least one character or action")
        return self


def _norm(text: str) -> str:
    return " ".join(text.replace("_", " ").lower().split())


def style_norms(recipe: Recipe) -> set[str]:
    """配方里画风和丢弃的 token：回归对照时从原图提示词里去掉它们。"""
    return {_norm(token.text) for zone in (recipe.prefix, recipe.suffix, recipe.dropped) for token in zone}


def subject_norms(recipe: Recipe) -> set[str]:
    """配方里手动留在主体的 token：分类说是风格也不去掉，以用户的划分为准。"""
    return {_norm(token.text) for token in recipe.subject}


def strip_style(
    prompt: str, norms: set[str], categories: dict[str, str], keep: set[str] | None = None
) -> tuple[str, list[str]]:
    """原图提示词去掉画风：配方里的画风 token，加上分类为画师/风格/质量/元信息的 token。返回（内容, 去掉的）。"""
    tokens = tokenize(prompt)
    kept = []
    removed = []
    keep = keep or set()
    for token in tokens.tokens:
        norm = _norm(token.text)
        if norm in norms or (norm not in keep and token_category(token.text, categories) in STYLE_CATEGORIES):
            removed.append(token.text)
        else:
            kept.append(token)
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
    settings: ArtistTestSettings, record: ImageRecord, subject: str, seed: int
) -> dict[str, Any]:
    params: dict[str, Any] = {"size": "custom", "n_samples": 1}
    caption = record.char_captions[0] if record.char_captions else None
    if caption and caption.positive.strip():
        params["character_prompts"] = {
            "mode": "explicit",
            "captions": [{"positive": caption.positive, "negative": caption.negative}],
            "add_male_caption": True,
        }
    return {
        "compose": {"prompt": subject, "negative": ""},
        "render": {
            "backend": "novelai",
            "artist": settings.artist,
            "width": settings.width or record.width or 1024,
            "height": settings.height or record.height or 1024,
            "seed": seed,
            "params": params,
        },
    }


def matrix_cells(settings: ArtistTestSettings) -> list[tuple[str | None, str | None]]:
    characters: list[str | None] = list(settings.characters) or [None]
    actions: list[str | None] = list(settings.actions) or [None]
    return [(character, action) for character in characters for action in actions]


def matrix_payload(settings: ArtistTestSettings, character: str | None, action: str | None, seed: int) -> dict[str, Any]:
    nodes = {}
    if character:
        nodes["character"] = character
    if action:
        nodes["action"] = action
    width, height = (settings.width, settings.height) if settings.width and settings.height else DEFAULT_MATRIX_SIZE
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
