"""配方探针：在保存好的配方上只改一处，用同一个种子出图，看画风对这处改动的反应。

- 替换角色：原角色在哪（主体或某条角色提示词）就在哪去掉它的名字和外貌（可选连服装一起），换成素材库里的角色，
  动作等其他 tag 照留，看画风换了人还稳不稳；
- 消融测试：画风前缀、后缀里每次去掉一个（或一组）token，和完整配方比，看哪些 token 真的在起作用。

两种都可以带一张“完整配方”的基准图，其余每张和基准图算相似度。
"""

from __future__ import annotations

import random
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .classify import token_category
from .recipe import Recipe, RecipeToken


MAX_SWAP_CHARACTERS = 4
MAX_ABLATION_UNITS = 12
# 换角色时从主体里去掉的类别；服装另有开关。
IDENTITY_CATEGORIES = ("character", "appearance")
CLOTHING_CATEGORY = "clothing"
_GENDER_RE = re.compile(r"^(girl|boy|woman|man|other|1girl|1boy)$", re.IGNORECASE)


class SwapCharacter(BaseModel):
    """素材库里的一个角色；tags 是素材块筛过之后要用的 tag。"""

    ref: str
    name: str
    tags: list[str] = Field(min_length=1)


class AblationUnit(BaseModel):
    """一次去掉的 token（画风前缀或后缀里的 token id），label 用于显示。"""

    label: str
    token_ids: list[str] = Field(min_length=1)


class ProbeSettings(BaseModel):
    kind: Literal["swap", "ablation"]
    characters: list[SwapCharacter] = Field(default_factory=list, max_length=MAX_SWAP_CHARACTERS)
    replace_clothing: bool = True
    # 换进哪里：auto 是原角色在哪就换哪（看角色名，没有角色名时看外貌 tag）；caption 换进第 caption_index 条角色提示词。
    target: Literal["auto", "subject", "caption"] = "auto"
    caption_index: int | None = Field(default=None, ge=0)
    units: list[AblationUnit] = Field(default_factory=list, max_length=MAX_ABLATION_UNITS)
    include_baseline: bool = True
    seed_mode: Literal["source", "random", "fixed"] = "source"
    seed: int | None = Field(default=None, ge=0, le=4294967295)

    @model_validator(mode="after")
    def _check(self) -> "ProbeSettings":
        if self.seed_mode == "fixed" and self.seed is None:
            raise ValueError("seed_mode=fixed requires seed")
        if self.kind == "swap" and not self.characters:
            raise ValueError("swap needs at least one character")
        if self.kind == "ablation":
            if not self.units:
                raise ValueError("ablation needs at least one unit")
            # 消融要和完整配方比，基准图不能省。
            self.include_baseline = True
        return self


def probe_seed(settings: ProbeSettings, source_seed: int | None) -> int:
    if settings.seed_mode == "fixed" and settings.seed is not None:
        return settings.seed
    if settings.seed_mode == "source" and source_seed is not None:
        return int(source_seed)
    return random.randint(0, 2**32 - 1)


def probe_variants(
    recipe: Recipe, settings: ProbeSettings, categories: dict[str, str]
) -> list[tuple[Recipe, dict[str, Any]]]:
    """每张图用的配方和它在 run 里的说明（label、role、改了什么）。"""
    variants: list[tuple[Recipe, dict[str, Any]]] = []
    if settings.include_baseline:
        variants.append((recipe, {"label": "完整配方", "role": "baseline"}))
    if settings.kind == "swap":
        for character in settings.characters:
            variants.append(swap_character(recipe, character, categories, settings))
    else:
        for unit in settings.units:
            variants.append(ablate(recipe, unit))
    return variants


def _token(text: str, origin: str) -> RecipeToken:
    return RecipeToken(text=text, origins=[origin])


def _is_card_token(token: RecipeToken) -> bool:
    return any(origin.startswith("character:") for origin in token.origins)


def _strip_identity(
    tokens: list[RecipeToken], remove: set[str], categories: dict[str, str]
) -> tuple[list[RecipeToken], list[str], int | None]:
    """去掉原角色的 token（角色卡加进来的、或类别在 remove 里的），性别词留着。返回（剩下的, 去掉的, 第一个去掉的位置）。"""
    kept: list[RecipeToken] = []
    removed: list[str] = []
    first: int | None = None
    for token in tokens:
        if not _GENDER_RE.match(token.text.strip()) and (
            _is_card_token(token) or token_category(token.text, categories) in remove
        ):
            removed.append(token.text)
            if first is None:
                first = len(kept)
            continue
        kept.append(token)
    return kept, removed, first


def _is_name(token: RecipeToken, categories: dict[str, str]) -> bool:
    return not _GENDER_RE.match(token.text.strip()) and (
        _is_card_token(token) or token_category(token.text, categories) == "character"
    )


def _looks_count(tokens: list[RecipeToken], categories: dict[str, str]) -> int:
    return sum(1 for token in tokens if token_category(token.text, categories) == "appearance")


def swap_target(recipe: Recipe, settings: ProbeSettings, categories: dict[str, str]) -> int | None:
    """换进哪条角色提示词；None 是主体。没启用角色提示词时总是主体。"""
    captions = recipe.character.captions if recipe.character.enabled else []
    if settings.target == "subject" or not captions:
        return None
    if settings.target == "caption" or settings.caption_index is not None:
        index = settings.caption_index or 0
        return index if index < len(captions) else None
    # 原角色在哪就换哪：先找角色名（角色提示词优先，主体里常常也会再写一遍），没有角色名时看外貌 tag 多的那处。
    for index, caption in enumerate(captions):
        if any(_is_name(token, categories) for token in caption.tokens):
            return index
    if any(_is_name(token, categories) for token in recipe.subject):
        return None
    looks = [_looks_count(caption.tokens, categories) for caption in captions]
    best = max(range(len(captions)), key=lambda index: looks[index])
    return best if looks[best] > _looks_count(recipe.subject, categories) else None


def swap_character(
    recipe: Recipe, character: SwapCharacter, categories: dict[str, str], settings: ProbeSettings
) -> tuple[Recipe, dict[str, Any]]:
    origin = f"character:{character.ref}"
    tags = list(dict.fromkeys(tag.strip() for tag in character.tags if tag.strip()))
    captions = recipe.character.captions
    caption_index = swap_target(recipe, settings, categories)

    identity = set(IDENTITY_CATEGORIES)
    if settings.replace_clothing:
        identity.add(CLOTHING_CATEGORY)
    # 换进角色提示词时，主体里只去掉角色名（外貌、服装多半属于别的角色或画面）；换进主体时外貌、服装一起换。
    into_caption = caption_index is not None
    subject, removed, insert_at = _strip_identity(recipe.subject, {"character"} if into_caption else identity, categories)

    new_captions = list(captions)
    if caption_index is not None:
        # 角色提示词里也可能有动作卡加进来的 tag：只换角色本身，其余照留。
        old = captions[caption_index]
        tokens, caption_removed, at = _strip_identity(old.tokens, identity, categories)
        removed.extend(caption_removed)
        if not any(_GENDER_RE.match(token.text.strip()) for token in tokens) and not any(_GENDER_RE.match(tag) for tag in tags):
            tags = ["girl", *tags]
        if at is None:
            at = sum(1 for token in tokens[:1] if _GENDER_RE.match(token.text.strip()))
        tokens[at:at] = [_token(tag, origin) for tag in tags]
        new_captions[caption_index] = old.model_copy(update={"tokens": tokens})
        target = f"角色提示词 #{caption_index + 1}"
    else:
        if insert_at is None:
            # 没有可替换的：放在开头的人数 tag 后面。
            insert_at = 0
            while insert_at < len(subject) and token_category(subject[insert_at].text, categories) == "count":
                insert_at += 1
        subject[insert_at:insert_at] = [_token(tag, origin) for tag in tags]
        target = "主体"
        if recipe.character.enabled and len(captions) == 1:
            # 角色在主体、只有一条角色提示词（多半写的是动作）：它里面的外貌、服装也是这个角色的，一起去掉。
            tokens, caption_removed, _ = _strip_identity(captions[0].tokens, identity, categories)
            removed.extend(caption_removed)
            new_captions[0] = captions[0].model_copy(update={"tokens": tokens})

    variant = recipe.model_copy(
        update={"subject": subject, "character": recipe.character.model_copy(update={"captions": new_captions})}
    )
    meta = {
        "label": character.name,
        "role": "variant",
        "character": character.ref,
        "target": target,
        "removed": removed,
        "added": tags,
    }
    return variant, meta


def ablate(recipe: Recipe, unit: AblationUnit) -> tuple[Recipe, dict[str, Any]]:
    ids = set(unit.token_ids)
    style_ids = {token.id for token in (*recipe.prefix, *recipe.suffix)}
    missing = ids - style_ids
    if missing:
        raise ValueError(f"消融的 token 不在画风前缀或后缀里（配方可能已经改过）：{', '.join(sorted(missing))}")
    removed = [token.text for token in (*recipe.prefix, *recipe.suffix) if token.id in ids]
    variant = recipe.model_copy(
        update={
            "prefix": [token for token in recipe.prefix if token.id not in ids],
            "suffix": [token for token in recipe.suffix if token.id not in ids],
        }
    )
    return variant, {"label": unit.label, "role": "variant", "token_ids": sorted(ids), "removed": removed}
