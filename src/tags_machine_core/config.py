from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

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


class WebConfig(BaseModel):
    project_requires: list[str] = Field(default_factory=list)


class NovelAIConfig(BaseModel):
    base_url: str = "https://image.novelai.net"
    access_token: str | None = None
    access_token_env: str = "NAI_ACCESS_TOKEN"
    timeout: int = 120
    retry: int = 3
    retry_interval: float | None = None
    request_interval: float = 0.0


COMFYUI_TARGET_ENV = "TAGS_MACHINE_CORE_COMFYUI_TARGET"
DEFAULT_COMFYUI_TARGET = "default"


class ComfyUIAuthConfig(BaseModel):
    """请求 ComfyUI 时附带的鉴权头。密钥放环境变量，配置里只写变量名。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "bearer"] = "none"
    token: str | None = None
    token_env: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    header_envs: dict[str, str] = Field(default_factory=dict)


class ComfyUIStatusProbeConfig(BaseModel):
    """Web 显示目标是否在线的方式，查询状态不能把 serverless 容器拉起来。

    auto：本机地址探测 /system_stats，其它地址不探测；http：总是探测 /system_stats；
    modal：用 Modal API 读取函数当前的容器数（需要安装 modal SDK）；none：不显示。
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["auto", "none", "http", "modal"] = "auto"
    app: str | None = None
    function: str | None = None
    idle_shutdown_seconds: float | None = None


class ComfyUIConnectionConfig(BaseModel):
    """一个 ComfyUI 目标的连接设置；顶层 comfyui 字段也是同一套。"""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    transport: Literal["native"] = "native"
    base_url: str = "http://127.0.0.1:8188"
    timeout: int = 300
    poll_interval: float = 1.0
    max_wait_seconds: float | None = 600
    retry: int = 3
    retry_interval: float = 2.0
    # posix：提交前把模型路径里的 "\\" 改成 "/"，用于 Linux 上的 ComfyUI。
    path_style: Literal["native", "posix"] = "native"
    # 声明了 output_nodes 时，只提交这些输出节点的上游子图。
    prune_to_output_nodes: bool = True
    # >0 时首次提交前轮询 /system_stats，等待 serverless 冷启动。
    cold_start_wait_seconds: float = 0
    # serverless 目标缩容后结果会丢，应关闭只排队不轮询的模式。
    allow_no_wait: bool = True
    auth: ComfyUIAuthConfig = Field(default_factory=ComfyUIAuthConfig)
    status_probe: ComfyUIStatusProbeConfig = Field(default_factory=ComfyUIStatusProbeConfig)


class ResolvedComfyUITarget(ComfyUIConnectionConfig):
    name: str


class ComfyUIConfig(ComfyUIConnectionConfig):
    """ComfyUI 配置。

    不写 targets 时，顶层字段就是唯一目标 "default"（旧配置保持原样可用）。
    写了 targets 时，每个目标只需写和顶层不同的字段，其余继承顶层。
    选择顺序：--comfyui-target > TAGS_MACHINE_CORE_COMFYUI_TARGET > default_target。
    """

    model_config = ConfigDict(extra="ignore")

    default_target: str | None = None
    targets: dict[str, ComfyUIConnectionConfig] = Field(default_factory=dict)

    def resolve_target(self, name: str | None = None) -> ResolvedComfyUITarget:
        selected = name or self.default_target
        base = self.model_dump(include=set(ComfyUIConnectionConfig.model_fields))
        if not self.targets:
            if selected not in (None, DEFAULT_COMFYUI_TARGET):
                raise ValueError(
                    f"Unknown ComfyUI target {selected!r}: config has no comfyui.targets"
                )
            return ResolvedComfyUITarget(name=DEFAULT_COMFYUI_TARGET, **base)
        if selected is None:
            if len(self.targets) != 1:
                raise ValueError(
                    "comfyui.targets has several entries; set comfyui.default_target, "
                    f"{COMFYUI_TARGET_ENV} or --comfyui-target"
                )
            selected = next(iter(self.targets))
        target = self.targets.get(selected)
        if target is None:
            allowed = ", ".join(self.targets)
            raise ValueError(f"Unknown ComfyUI target {selected!r}; expected one of: {allowed}")
        overrides = target.model_dump(include=target.model_fields_set)
        return ResolvedComfyUITarget(name=selected, **{**base, **overrides})

    def target_names(self) -> list[str]:
        return list(self.targets) or [DEFAULT_COMFYUI_TARGET]

    def with_default_target(self, name: str) -> ComfyUIConfig:
        return self.model_copy(update={"default_target": name})

    def with_timeout(self, timeout: int) -> ComfyUIConfig:
        targets = {
            name: target.model_copy(update={"timeout": timeout})
            if "timeout" in target.model_fields_set
            else target
            for name, target in self.targets.items()
        }
        return self.model_copy(update={"timeout": timeout, "targets": targets})


class SDConfig(BaseModel):
    base_url: str = "http://127.0.0.1:7860"
    timeout: int = 120


class AppConfig(BaseModel):
    legacy: LegacyConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    web: WebConfig = Field(default_factory=WebConfig)
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
    return apply_env_overrides(AppConfig.model_validate(data))


def apply_env_overrides(config: AppConfig) -> AppConfig:
    target = os.environ.get(COMFYUI_TARGET_ENV, "").strip()
    if target:
        config = config.model_copy(
            update={"comfyui": config.comfyui.with_default_target(target)}
        )
    return config


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
