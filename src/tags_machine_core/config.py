from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from tags_machine_core.nodes.artist_input_filter import ArtistInputFilterConfig
from tags_machine_core.policies import (
    PromptPolicyProvider,
    PromptPolicySource,
    PromptPolicyTemplateResolver,
)


class LegacyConfig(BaseModel):
    tags_machine_root: Path
    design_root: Path


class RuntimeConfig(BaseModel):
    cache_dir: Path = Path("cache")
    output_dir: Path = Path("outputs")


class DefaultsConfig(BaseModel):
    backend: str = "novelai"
    image_format: str = "png"


class GenerationConfig(BaseModel):
    executor: Literal["core_novelai_client", "ai_image_gateway_raw"] = "core_novelai_client"


class LoggingConfig(BaseModel):
    level: str = "error"


class NovelAIConfig(BaseModel):
    base_url: str = "https://image.novelai.net"
    access_token: str | None = None
    access_token_env: str = "NAI_ACCESS_TOKEN"
    timeout: int = 120
    retry: int = 3
    retry_interval: float | None = None
    request_interval: float = 0.0


class ComfyUIConfig(BaseModel):
    base_url: str = "http://127.0.0.1:8188"
    timeout: int = 300
    poll_interval: float = 1.0
    max_wait_seconds: float | None = 600
    retry: int = 3
    retry_interval: float = 2.0


class SDConfig(BaseModel):
    base_url: str = "http://127.0.0.1:7860"
    timeout: int = 120


class AppConfig(BaseModel):
    legacy: LegacyConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    artist_input_filter: ArtistInputFilterConfig = Field(
        default_factory=ArtistInputFilterConfig
    )
    prompt_policy_template_root: Path | None = None
    prompt_policy: PromptPolicySource = Field(
        default_factory=lambda: PromptPolicySource(require="default")
    )
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


def build_prompt_policy_provider(
    config: AppConfig,
    *,
    config_path: str | Path | None = None,
) -> PromptPolicyProvider:
    relative_to = Path(config_path).resolve().parent if config_path else None
    template_root = config.prompt_policy_template_root
    if template_root is not None and not template_root.is_absolute() and relative_to is not None:
        template_root = (relative_to / template_root).resolve()
    resolver = PromptPolicyTemplateResolver(template_root=template_root)
    return PromptPolicyProvider(
        template_resolver=resolver,
        project_default_source=config.prompt_policy,
        relative_to=relative_to,
    )
