"""配方：正在调的画风。一份配方对应导出后的一个 artist（tags.txt）。

- prefix / suffix 是画风（导出到 tags.txt 第 1、3 行），subject 和 character 只用于测试出图；
- 每个 token 记录来源（原图、角色卡、动作卡、手打），素材卡片按来源整体移除；
- 保存时版本号加一，旧版本留在 history 目录，便于回看和对比。
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .metadata import ImageRecord, read_source_parameters
from .tokens import Token, TokenList, serialize, tokenize


RECIPE_SCHEMA = "tags-machine-core.style-lab.recipe/v1"
QUALITY_FLAG = "not_quailty_prompts"

# 画风参数：随配方保存、导出到 gen_json。宽高、种子、张数是每次出图的运行设置，不属于画风。
STYLE_PARAM_KEYS = (
    "sampler",
    "steps",
    "scale",
    "cfg_rescale",
    "noise_schedule",
    "sm",
    "sm_dyn",
    "dynamic_thresholding",
    "uncond_scale",
    "skip_cfg_above_sigma",
    "skip_cfg_below_sigma",
    "prefer_brownian",
    "deliberate_euler_ancestral_bug",
    "legacy",
    "legacy_v3_extend",
    "reference_strength_multiple",
    "reference_information_extracted_multiple",
    "uncond_per_vibe",
    "wonky_vibe_correlation",
    "add_original_image",
)
VIBE_IMAGE_KEY = "reference_image_multiple"


class RecipeToken(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    text: str
    sep: str = ""
    origins: list[str] = Field(default_factory=lambda: ["source"])


class RecipeCaption(BaseModel):
    """一条角色提示词（v4 char_caption），center 是原图里的位置，没有时按画面中心。"""

    tokens: list[RecipeToken] = Field(default_factory=list)
    negative: list[RecipeToken] = Field(default_factory=list)
    center: dict[str, float] | None = None


class RecipeCharacter(BaseModel):
    enabled: bool = False
    captions: list[RecipeCaption] = Field(default_factory=list)
    # 原图是否按位置摆放角色（v4_prompt.use_coords）；关着时位置不起作用。
    use_coords: bool = False
    # 默认不按主体里的 1boy 等自动补男角色：复刻时原图的角色提示词是手写的，自动补的会多出来。
    add_male_caption: bool = False

    @model_validator(mode="before")
    @classmethod
    def _single_caption_layout(cls, data: Any) -> Any:
        # 旧配方只有一条角色提示词，tokens / negative 直接挂在 character 上。
        if not isinstance(data, dict) or ("tokens" not in data and "negative" not in data):
            return data
        data = dict(data)
        tokens = data.pop("tokens", None) or []
        negative = data.pop("negative", None) or []
        if "captions" not in data:
            data["captions"] = [{"tokens": tokens, "negative": negative}] if tokens or negative else []
        return data


class RecipeMaterial(BaseModel):
    """素材架上的一块：选中的角色/动作卡片，excluded 是在卡片里筛掉不要的 tag。"""

    role: Literal["character", "action"]
    ref: str
    name: str
    excluded: list[str] = Field(default_factory=list)


class Recipe(BaseModel):
    schema_id: str = Field(default=RECIPE_SCHEMA, alias="schema")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str
    version: int = 1
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    source_image_id: str | None = None
    group_id: str | None = None
    stage: Literal["split", "edit"] = "split"
    locked: bool = False
    prefix: list[RecipeToken] = Field(default_factory=list)
    subject: list[RecipeToken] = Field(default_factory=list)
    suffix: list[RecipeToken] = Field(default_factory=list)
    dropped: list[RecipeToken] = Field(default_factory=list)
    character: RecipeCharacter = Field(default_factory=RecipeCharacter)
    materials: list[RecipeMaterial] = Field(default_factory=list)
    negative: list[RecipeToken] = Field(default_factory=list)
    model: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    use_source_vibe: bool = True
    flags: list[str] = Field(default_factory=lambda: [QUALITY_FLAG])
    notes: str = ""

    model_config = {"populate_by_name": True}


class RecipeConflictError(RuntimeError):
    pass


def tokens_from_text(text: str, origin: str = "source") -> list[RecipeToken]:
    return [RecipeToken(text=token.text, sep=token.sep, origins=[origin]) for token in tokenize(text).tokens]


def tokens_text(tokens: list[RecipeToken]) -> str:
    return serialize(TokenList(tokens=[Token(text=token.text, sep=token.sep) for token in tokens]))


def line_text(tokens: list[RecipeToken]) -> str:
    """单行文本：tags.txt 一行就是一段，token 之间的换行改成逗号，预览、导出、读回三者一致。"""
    # 分隔符去掉换行后没有逗号的，serialize 会补 ", "。
    flat = [
        Token(text=re.sub(r"\s*[\r\n]+\s*", " ", token.text), sep=re.sub(r"[\r\n]+", "", token.sep))
        for token in tokens
    ]
    return serialize(TokenList(tokens=flat)).strip(" ,")


def recipe_from_image(record: ImageRecord, *, name: str | None = None, group_id: str | None = None) -> Recipe:
    """初始状态：原图整段提示词都在主体里（划分阶段），负面、角色提示词和画风参数取自原图。"""
    params, _ = read_source_parameters(Path(record.path))
    style_params = {key: params[key] for key in STYLE_PARAM_KEYS if key in params}
    v4_prompt = params.get("v4_prompt")
    captions = [
        RecipeCaption(
            tokens=tokens_from_text(caption.positive),
            negative=tokens_from_text(caption.negative),
            center=caption.centers[0] if caption.centers else None,
        )
        for caption in record.char_captions
    ]
    return Recipe(
        name=name or _default_name(record),
        source_image_id=record.id,
        group_id=group_id,
        subject=tokens_from_text(record.prompt),
        negative=tokens_from_text(record.negative_prompt),
        character=RecipeCharacter(
            enabled=any(caption.positive.strip() for caption in record.char_captions),
            captions=captions,
            use_coords=bool(isinstance(v4_prompt, dict) and v4_prompt.get("use_coords")),
        ),
        model=record.model,
        params=style_params,
        use_source_vibe=record.vibe.count > 0,
    )


def _default_name(record: ImageRecord) -> str:
    post = record.post
    label = post.title or post.post_id if post else None
    return f"配方 · {label or Path(record.path).stem}"


def artist_node(recipe: Recipe, *, source_path: str | None = None) -> dict[str, Any]:
    """把配方拼成和导出后读回来完全一样的 legacy artist 节点（tags.txt 第 1 行前缀、第 3 行后缀）。"""
    params = dict(recipe.params)
    # 旧画风缺省时渲染器按 True 处理；网页端文生图的元数据里没有这一项，按已有画风的写法显式写 false。
    params.setdefault("add_original_image", False)
    if recipe.model:
        params["model"] = recipe.model
    if recipe.use_source_vibe and source_path:
        source_params, _ = read_source_parameters(Path(source_path))
        images = source_params.get(VIBE_IMAGE_KEY) or []
        if images:
            params[VIBE_IMAGE_KEY] = list(images)
    else:
        params.pop("reference_strength_multiple", None)
        params.pop("reference_information_extracted_multiple", None)
    prefix = line_text(recipe.prefix)
    suffix = line_text(recipe.suffix)
    negative = line_text(recipe.negative)
    ref = f"style_lab/{recipe.id}"
    return {
        "schema": "tags-machine.artist/v1",
        "kind": "artist",
        "id": ref,
        "name": recipe.name,
        "renderers": {
            "novelai": {
                "legacy_compat": True,
                "artist_ref": ref,
                "path": "",
                "include_common_tags": False,
                "prompt_prefix": [prefix] if prefix else [],
                "prompt_suffix": [suffix] if suffix else [],
                "negative_prompt": [negative] if negative else [],
                "after_negative_prompt": [],
                "params": params,
                "flags": sorted(set(recipe.flags)),
            }
        },
    }


def character_prompts_param(recipe: Recipe) -> dict[str, Any] | None:
    if not recipe.character.enabled:
        return None
    captions = []
    for caption in recipe.character.captions:
        positive = tokens_text(caption.tokens).strip(" ,")
        if not positive:
            continue
        item: dict[str, Any] = {"positive": positive, "negative": tokens_text(caption.negative).strip(" ,")}
        if caption.center:
            item["center"] = dict(caption.center)
        captions.append(item)
    if not captions:
        return None
    return {
        "mode": "explicit",
        "captions": captions,
        "use_coords": recipe.character.use_coords,
        "add_male_caption": recipe.character.add_male_caption,
    }


class RecipeStore:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "recipes"
        self._lock = threading.RLock()

    def list(self) -> list[Recipe]:
        if not self.root.is_dir():
            return []
        recipes = []
        for path in self.root.glob("*.json"):
            try:
                recipes.append(Recipe.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(recipes, key=lambda recipe: recipe.updated_at, reverse=True)

    def get(self, recipe_id: str) -> Recipe:
        path = self._path(recipe_id)
        with self._lock:
            if not path.is_file():
                raise KeyError(recipe_id)
            return Recipe.model_validate_json(path.read_text(encoding="utf-8"))

    def create(self, recipe: Recipe) -> Recipe:
        with self._lock:
            if self._path(recipe.id).exists():
                raise RecipeConflictError(f"Recipe {recipe.id} already exists")
            self._write(recipe)
        return recipe

    def save(self, recipe: Recipe, *, base_version: int) -> Recipe:
        """保存新版本：base_version 必须等于当前版本，防止两个页面互相覆盖。"""
        with self._lock:
            current = self.get(recipe.id)
            if current.version != base_version:
                raise RecipeConflictError(f"Recipe {recipe.id} is at version {current.version}, not {base_version}")
            history = self.root / f"{recipe.id}.history"
            history.mkdir(parents=True, exist_ok=True)
            (history / f"v{current.version}.json").write_text(
                current.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
            )
            saved = recipe.model_copy(
                update={"version": current.version + 1, "updated_at": time.time(), "created_at": current.created_at}
            )
            self._write(saved)
            return saved

    def history(self, recipe_id: str) -> list[dict[str, Any]]:
        folder = self.root / f"{recipe_id}.history"
        if not folder.is_dir():
            return []
        items = []
        for path in folder.glob("v*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append({"version": data.get("version"), "updated_at": data.get("updated_at")})
        return sorted(items, key=lambda item: item["version"] or 0, reverse=True)

    def get_version(self, recipe_id: str, version: int) -> Recipe:
        current = self.get(recipe_id)
        if current.version == version:
            return current
        path = self.root / f"{recipe_id}.history" / f"v{version}.json"
        if not path.is_file():
            raise KeyError(f"{recipe_id}@{version}")
        return Recipe.model_validate_json(path.read_text(encoding="utf-8"))

    def delete(self, recipe_id: str) -> None:
        with self._lock:
            path = self._path(recipe_id)
            if not path.is_file():
                raise KeyError(recipe_id)
            path.unlink()

    def _path(self, recipe_id: str) -> Path:
        if not re.fullmatch(r"[\w-]+", recipe_id):
            raise KeyError(recipe_id)
        return self.root / f"{recipe_id}.json"

    def _write(self, recipe: Recipe) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(recipe.id)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(recipe.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        temp.replace(path)
