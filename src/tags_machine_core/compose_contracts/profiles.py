from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FORMATS_DIR = PROJECT_ROOT / "configs" / "prompt_formats"


class WeightSpec(BaseModel):
    syntaxes: list[Literal["brace", "numeric", "paren"]] = Field(default_factory=lambda: ["brace", "numeric"])
    preferred: str | None = None
    range: tuple[float, float] = (0.0, 3.0)


class LanguageSpec(BaseModel):
    allow_cjk: bool = False


class LengthSpec(BaseModel):
    tokenizer: Literal["clip", "t5", "qwen", "approx"] = "approx"
    max_tokens: int | None = None
    # 主提示词和各角色提示词加起来共用上限（NovelAI V4+ 官网规则）。
    shared_with_characters: bool = False
    # 超过上限时：error（会被截断）或 warn（只是效果变差）。估算出的数字一律只给警告。
    over_limit: Literal["error", "warn"] = "error"


class MultiCharacterSpec(BaseModel):
    supported: bool = False
    max: int = 1


class ForbidSpec(BaseModel):
    artist_tags: bool = True
    quality_tags: Literal["renderer", "allow"] | bool = "renderer"


class FormatProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    version: int = 1
    label: str = ""
    family: str = "novelai"
    models: list[str] = Field(default_factory=list)
    separator: str = ","
    newline: Literal["separator", "keep"] = "separator"
    weight: WeightSpec = Field(default_factory=WeightSpec)
    language: LanguageSpec = Field(default_factory=LanguageSpec)
    length: LengthSpec = Field(default_factory=LengthSpec)
    multi_character: MultiCharacterSpec = Field(default_factory=MultiCharacterSpec)
    forbid: ForbidSpec = Field(default_factory=ForbidSpec)
    validators: list[str] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label or self.id,
            "family": self.family,
            "models": self.models,
            "separator": self.separator,
            "newline": self.newline,
            "weight_syntaxes": self.weight.syntaxes,
            "weight_preferred": self.weight.preferred,
            "weight_range": list(self.weight.range),
            "allow_cjk": self.language.allow_cjk,
            "tokenizer": self.length.tokenizer,
            "max_tokens": self.length.max_tokens,
            "tokens_shared_with_characters": self.length.shared_with_characters,
            "multi_character": self.multi_character.model_dump(),
            "validators": self.validators,
        }

    def prompt_for_submit(self, text: str) -> str:
        """提交生图时的提示词：newline=separator 时把换行折成分隔符，空行和多余空白去掉。"""
        if self.newline == "keep":
            return text.strip()
        parts = [part.strip() for line in text.splitlines() for part in line.split(self.separator)]
        return f"{self.separator} ".join(part for part in parts if part)


def load_format_profiles(formats_dir: str | Path | None = None) -> dict[str, FormatProfile]:
    directory = Path(formats_dir) if formats_dir else DEFAULT_FORMATS_DIR
    profiles: dict[str, FormatProfile] = {}
    if not directory.is_dir():
        return profiles
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"格式 profile 必须是 YAML 映射：{path}")
        data.setdefault("id", path.stem)
        profile = FormatProfile.model_validate(data)
        profiles[profile.id] = profile
    return profiles
