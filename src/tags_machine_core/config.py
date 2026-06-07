from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LegacyConfig(BaseModel):
    tags_machine_root: Path
    design_root: Path


class RuntimeConfig(BaseModel):
    cache_dir: Path = Path("cache")
    output_dir: Path = Path("outputs")


class DefaultsConfig(BaseModel):
    backend: str = "novelai"
    image_format: str = "png"


class NovelAIConfig(BaseModel):
    base_url: str = "https://image.novelai.net"
    access_token_env: str = "NAI_ACCESS_TOKEN"
    timeout: int = 120
    retry: int = 3
    retry_interval: float | None = None


class ComfyUIConfig(BaseModel):
    base_url: str = "http://127.0.0.1:8188"
    timeout: int = 120


class SDConfig(BaseModel):
    base_url: str = "http://127.0.0.1:7860"
    timeout: int = 120


class AppConfig(BaseModel):
    legacy: LegacyConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    novelai: NovelAIConfig = Field(default_factory=NovelAIConfig)
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    sd: SDConfig = Field(default_factory=SDConfig)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in config file: {path}")
    return data


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    data = load_yaml(path)
    return AppConfig.model_validate(data)
