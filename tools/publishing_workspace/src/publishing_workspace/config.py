from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .logging import get_logger


WORKSPACE_SCHEMA = "publishing-workspace.workspace/v1"
LEGACY_WORKSPACE_SCHEMA = "tags-machine-core.publish-workspace/v1"
logger = get_logger(__name__)


class ActionResolutionConfig(BaseModel):
    enabled: bool = True
    design_root: str | None = None
    action_root_name: str = "动作改2"

    @field_validator("action_root_name")
    @classmethod
    def validate_action_root_name(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(
                "classification.action_resolution.action_root_name 不能为空"
            )
        return normalized


class ClassificationConfig(BaseModel):
    hierarchy: list[str] = Field(
        default_factory=lambda: ["artist", "character", "action_group", "action"]
    )
    missing_value: str = "unknown"
    skip_missing: bool = False
    action_resolution: ActionResolutionConfig = Field(default_factory=ActionResolutionConfig)

    @field_validator("missing_value")
    @classmethod
    def validate_missing_value(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("classification.missing_value 不能为空")
        return normalized

    @field_validator("hierarchy")
    @classmethod
    def validate_hierarchy(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if not normalized:
            raise ValueError("classification.hierarchy 不能为空")
        if len(set(normalized)) != len(normalized):
            raise ValueError("classification.hierarchy 不能包含重复维度")
        return normalized


class NeeViewExporterConfig(BaseModel):
    enabled: bool = True
    root: str = "workspace/exports"


class ShortcutExporterConfig(BaseModel):
    enabled: bool = False
    root: str = "workspace/exports"


class ExportersConfig(BaseModel):
    neev: NeeViewExporterConfig = Field(default_factory=NeeViewExporterConfig)
    windows_shortcut: ShortcutExporterConfig = Field(default_factory=ShortcutExporterConfig)


class MosaicModelConfig(BaseModel):
    filename: str
    url: str
    sha256: str

    @field_validator("filename", "url")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("mosaic model filename/url 不能为空")
        return normalized

    @field_validator("sha256")
    @classmethod
    def normalize_sha256(cls, value: str) -> str:
        normalized = str(value or "").strip().casefold()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("mosaic model sha256 必须是 64 位十六进制字符串")
        return normalized


def _default_mosaic_models() -> dict[str, MosaicModelConfig]:
    return {
        "yolo": MosaicModelConfig(
            filename="yolo/censor.pt",
            url=(
                "https://github.com/zhulinyv/anr_plugin_auto_mosaics/raw/main/"
                "models/yolo/censor.pt"
            ),
            sha256="62b18176b005ec5b8918d3fdd99323193ba2dd99c06e150de808087d37ebe009",
        ),
        "sam": MosaicModelConfig(
            filename="sams/sam_vit_b_01ec64.pth",
            url=(
                "https://huggingface.co/datasets/Xytpz/SAM_Models/resolve/main/"
                "sam_vit_b_01ec64.pth?download=true"
            ),
            sha256="ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912",
        ),
    }


class MosaicIntegrationConfig(BaseModel):
    provider: str = "anr_plugin_auto_mosaics"
    model_root: str | None = None
    models: dict[str, MosaicModelConfig] = Field(default_factory=_default_mosaic_models)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("integrations.mosaic.provider 不能为空")
        return normalized


class IntegrationsConfig(BaseModel):
    mosaic: MosaicIntegrationConfig = Field(default_factory=MosaicIntegrationConfig)


class PublishingWorkspaceConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(
        default=WORKSPACE_SCHEMA,
        alias="schema",
    )
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    exporters: ExportersConfig = Field(default_factory=ExportersConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    image_extensions: list[str] = Field(
        default_factory=lambda: [".png", ".jpg", ".jpeg", ".webp"]
    )

    @field_validator("schema_id")
    @classmethod
    def validate_schema(cls, value: str) -> str:
        if value != WORKSPACE_SCHEMA:
            raise ValueError(f"不支持的 Publishing workspace schema：{value}")
        return value


class WorkspacePaths(BaseModel):
    root: Path
    workspace: Path
    config: Path
    catalog: Path
    backups: Path
    imports: Path
    exports: Path
    cache: Path
    state: Path
    tasks: Path
    plans: Path

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_root(cls, root: str | Path) -> "WorkspacePaths":
        resolved = Path(root).expanduser().resolve()
        workspace = resolved / "workspace"
        return cls(
            root=resolved,
            workspace=workspace,
            config=workspace / "workspace.yaml",
            catalog=workspace / "catalog.sqlite",
            backups=workspace / "backups",
            imports=workspace / "imports",
            exports=workspace / "exports",
            cache=workspace / "cache",
            state=workspace / "state",
            tasks=resolved / "tasks",
            plans=resolved / "plans",
        )

    @property
    def default_mosaic_models(self) -> Path:
        """返回随 publishing_workspace 分发的默认模型目录。"""
        return Path(__file__).resolve().parents[2] / "models" / "anr_plugin_auto_mosaics"

    def resolve_mosaic_model_root(self, configured_root: str | None) -> Path:
        if configured_root is None or not str(configured_root).strip():
            return self.default_mosaic_models
        root = Path(configured_root).expanduser()
        if not root.is_absolute():
            root = self.root / root
        return root.resolve()


def init_workspace(root: str | Path) -> tuple[WorkspacePaths, PublishingWorkspaceConfig, bool]:
    paths = WorkspacePaths.from_root(root)
    for directory in (
        paths.root,
        paths.workspace,
        paths.backups,
        paths.imports,
        paths.exports,
        paths.cache,
        paths.state,
        paths.tasks,
        paths.plans,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    created = not paths.config.exists()
    if created:
        config = PublishingWorkspaceConfig()
        _write_yaml_atomic(paths.config, config.model_dump(mode="json", by_alias=True))
    else:
        config = _read_config(paths.config)
    return paths, config, created


def load_workspace(root: str | Path) -> tuple[WorkspacePaths, PublishingWorkspaceConfig]:
    paths = WorkspacePaths.from_root(root)
    if not paths.config.is_file():
        raise FileNotFoundError(f"Publishing 工作区尚未初始化：{paths.config}")
    return paths, _read_config(paths.config)


def _read_config(path: Path) -> PublishingWorkspaceConfig:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 Publishing 配置：{path}：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Publishing 配置顶层必须是对象：{path}")
    migrated = data.get("schema") == LEGACY_WORKSPACE_SCHEMA
    if migrated:
        data["schema"] = WORKSPACE_SCHEMA
    config = PublishingWorkspaceConfig.model_validate(data)
    if migrated:
        backup = path.with_name(f"{path.name}.tags-machine-core-v1.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        _write_yaml_atomic(path, data)
        logger.warning("Publishing workspace 配置已升级：%s，备份：%s", path, backup)
    return config


def _write_yaml_atomic(path: Path, data: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)
