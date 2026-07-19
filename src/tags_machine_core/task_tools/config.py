from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from .registry import OperationRegistry


class OperationPlacement(StrEnum):
    QUICK = "quick"
    LAUNCHER = "launcher"
    BOTH = "both"


class OperationOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    placement: OperationPlacement | None = None
    label: str | None = None
    order: int | None = None


class TaskToolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_: Literal["prompt-atelier.task-tools/v1"] = Field(
        default="prompt-atelier.task-tools/v1",
        validation_alias="schema",
        serialization_alias="schema",
    )
    log_level: Literal["trace", "info", "warning", "error"] = "error"
    operations: dict[str, OperationOverride] = Field(default_factory=dict)


def _yaml_error_detail(exc: yaml.YAMLError) -> str:
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return "\u4f4d\u7f6e\u4e0d\u660e"
    return f"\u7b2c {mark.line + 1} \u884c\uff0c\u7b2c {mark.column + 1} \u5217"


def _validation_error_detail(exc: ValidationError) -> str:
    location_parts = exc.errors(include_url=False)[0]["loc"]
    field_names = {
        "schema": "\u914d\u7f6e\u683c\u5f0f",
        "schema_": "\u914d\u7f6e\u683c\u5f0f",
        "log_level": "\u65e5\u5fd7\u7ea7\u522b",
        "operations": "\u64cd\u4f5c\u914d\u7f6e",
        "enabled": "\u542f\u7528\u72b6\u6001",
        "placement": "\u64cd\u4f5c\u4f4d\u7f6e",
        "label": "\u64cd\u4f5c\u6807\u7b7e",
        "order": "\u64cd\u4f5c\u6392\u5e8f",
    }
    rendered: list[str] = []
    for index, part in enumerate(location_parts):
        if index == 1 and location_parts[0] == "operations":
            rendered.append(f"\u64cd\u4f5c {part}")
        else:
            rendered.append(field_names.get(str(part), str(part)))
    return "\uff1a".join(rendered)


def load_task_tools_config(
    path: Path | None,
    *,
    registry: "OperationRegistry",
) -> TaskToolsConfig:
    data: dict[str, object] = {}
    if path is not None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                f"\u4efb\u52a1\u5de5\u5177\u914d\u7f6e\u8bfb\u53d6\u5931\u8d25\uff1a{path}"
            ) from exc
        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            detail = _yaml_error_detail(exc)
            raise ValueError(
                f"\u4efb\u52a1\u5de5\u5177\u914d\u7f6e YAML \u89e3\u6790\u5931\u8d25\uff1a{path}\uff08{detail}\uff09"
            ) from exc
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise ValueError(f"\u4efb\u52a1\u5de5\u5177\u914d\u7f6e\u5fc5\u987b\u662f\u6620\u5c04\uff1a{path}")
        data = loaded
    try:
        config = TaskToolsConfig.model_validate(data)
    except ValidationError as exc:
        detail = _validation_error_detail(exc)
        raise ValueError(
            f"\u4efb\u52a1\u5de5\u5177\u914d\u7f6e\u6821\u9a8c\u5931\u8d25\uff1a{path}\uff08{detail}\uff09"
        ) from exc
    unknown = sorted(set(config.operations) - set(registry.ids()))
    if unknown:
        raise ValueError(f"\u672a\u77e5\u7684\u4efb\u52a1\u5de5\u5177\u64cd\u4f5c\uff1a{unknown[0]}")
    for spec in registry.all():
        override = config.operations.setdefault(spec.id, OperationOverride())
        if override.placement is None:
            override.placement = spec.default_placement
        if override.order is None:
            override.order = spec.default_order
        if override.label is None:
            override.label = spec.default_label
    return config
