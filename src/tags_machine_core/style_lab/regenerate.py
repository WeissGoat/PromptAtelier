from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from tags_machine_core.clients.novelai import normalize_novelai_model
from tags_machine_core.renderers.sizes import STANDARD_SIZE_PRESETS

from .metadata import ImageRecord, read_source_parameters, resolve_actual_prompts


MAX_REGEN_COUNT = 8
OVERRIDE_KEYS = ("model", "steps", "scale", "cfg_rescale", "sampler", "noise_schedule")
# 尺寸：原图 / 自定义 / 每张随机抽竖横方 / 按竖、横、方依次轮换。
SizeMode = Literal["source", "custom", "random", "loop"]
SIZE_CYCLE = ("portrait", "landscape", "square")


class RegenSettings(BaseModel):
    count: int = Field(default=1, ge=1, le=MAX_REGEN_COUNT)
    seed_mode: Literal["source", "random", "fixed"] = "source"
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    size_mode: SizeMode = "source"
    width: int | None = Field(default=None, ge=64, le=4096)
    height: int | None = Field(default=None, ge=64, le=4096)
    overrides: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "RegenSettings":
        if self.seed_mode == "fixed" and self.seed is None:
            raise ValueError("seed_mode=fixed requires seed")
        if self.size_mode == "custom" and (self.width is None or self.height is None):
            raise ValueError("size_mode=custom requires width and height")
        unknown = set(self.overrides) - set(OVERRIDE_KEYS)
        if unknown:
            raise ValueError(f"Unsupported overrides: {', '.join(sorted(unknown))}")
        self.overrides = {key: value for key, value in self.overrides.items() if value not in (None, "")}
        return self


def plan_seeds(settings: RegenSettings, source_seed: int | None, *, rng: random.Random | None = None) -> list[int]:
    rng = rng or random.Random()
    if settings.seed_mode == "random" or (settings.seed_mode == "source" and source_seed is None):
        return [rng.randint(0, 2**32 - 1) for _ in range(settings.count)]
    base = settings.seed if settings.seed_mode == "fixed" else source_seed
    assert base is not None
    return [(base + offset) % 2**32 for offset in range(settings.count)]


def plan_sizes(
    mode: str, count: int, width: int | None = None, height: int | None = None, *, rng: random.Random | None = None
) -> list[tuple[int, int] | None]:
    """每张图的宽高；None 表示用原图尺寸。random 每张各抽一个竖横方，loop 按竖、横、方依次轮换。"""
    if mode == "custom" and width and height:
        return [(int(width), int(height))] * count
    if mode == "random":
        rng = rng or random.Random()
        return [STANDARD_SIZE_PRESETS[rng.choice(SIZE_CYCLE)] for _ in range(count)]
    if mode == "loop":
        return [STANDARD_SIZE_PRESETS[SIZE_CYCLE[index % len(SIZE_CYCLE)]] for index in range(count)]
    return [None] * count


def expected_diff_keys(settings: RegenSettings, record: ImageRecord) -> set[str]:
    """本次设置主动改动的参数；对照时这些差异不算链路问题。"""
    keys = set(settings.overrides)
    if settings.seed_mode != "source" or record.seed is None or settings.count > 1:
        keys.add("seed")
    if settings.size_mode != "source":
        keys.update({"width", "height"})
    return keys


def build_regen_request(
    record: ImageRecord, settings: RegenSettings, seed: int, size: tuple[int, int] | None = None
) -> dict[str, Any]:
    """用源图的完整参数组装 render_request，不经过 Composer；vibe 由执行层按 source_image_path 补回。"""
    params, _ = read_source_parameters(Path(record.path))
    if not params:
        raise ValueError(f"Image has no NovelAI metadata: {record.rel_path}")
    prompt, negative = record.prompt, record.negative_prompt
    actual = params.get("actual_prompts")
    # 提示词里有随机选择（||a|b||）：按原图选中的那项发，不让 NovelAI 重新挑。
    params = resolve_actual_prompts(dict(params))
    if isinstance(actual, dict):
        prompt = str((actual.get("prompt") or {}).get("base_caption") or prompt)
        negative = str((actual.get("negative_prompt") or {}).get("base_caption") or negative)
    # 原图尺寸按元数据里生成时的尺寸：放大过的图文件尺寸会超出 NovelAI 的上限。
    if size is None and settings.size_mode == "custom":
        size = (settings.width or 0, settings.height or 0)
    width = size[0] if size else (params.get("width") or record.width or 1024)
    height = size[1] if size else (params.get("height") or record.height or 1024)
    for key in ("steps", "scale", "cfg_rescale", "sampler", "noise_schedule"):
        if key in settings.overrides:
            params[key] = settings.overrides[key]
    model = normalize_novelai_model(str(settings.overrides.get("model") or record.model or ""))
    params.update({"seed": seed, "width": int(width), "height": int(height), "n_samples": 1})
    return {
        "backend": "novelai",
        "prompt": prompt,
        "negative_prompt": negative,
        "model": model,
        "seed": seed,
        "size": {"width": int(width), "height": int(height)},
        "params": params,
        "meta": {
            "source": "style_lab_regenerate",
            "source_image_path": record.path,
        },
    }
