from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.policies.source import PromptPolicySource


@dataclass(frozen=True)
class ResolvedPromptPolicySource:
    mapping: dict[str, Any]
    template: str | None
    template_hash: str | None


class PromptPolicyTemplateResolver:
    def __init__(self, template_root: str | Path | None = None):
        self.template_root = Path(template_root).resolve() if template_root else None
        self.builtin_root = Path(__file__).resolve().parent / "templates"

    def resolve(
        self,
        source: PromptPolicySource | dict[str, Any] | None,
        *,
        implicit_template: str | None = "default",
        relative_to: str | Path | None = None,
    ) -> ResolvedPromptPolicySource:
        source_model = _coerce_source(source)
        raw = source_model.as_mapping() if source_model is not None else {}
        template_ref = raw.pop("require", None) or implicit_template
        template_mapping: dict[str, Any] = {}
        template_names: list[str] = []
        if template_ref:
            template_mapping, template_names = self._load_template_chain(
                str(template_ref),
                relative_to=Path(relative_to).resolve() if relative_to else None,
                stack=[],
            )
        merged = deep_merge(template_mapping, raw)
        template_hash = _mapping_hash(merged) if template_ref else None
        return ResolvedPromptPolicySource(
            mapping=merged,
            template=" -> ".join(template_names) if template_names else None,
            template_hash=template_hash,
        )

    def _load_template_chain(
        self,
        reference: str,
        *,
        relative_to: Path | None,
        stack: list[Path],
    ) -> tuple[dict[str, Any], list[str]]:
        path = self._resolve_template_path(reference, relative_to=relative_to)
        if path in stack:
            cycle = " -> ".join(str(item) for item in [*stack, path])
            raise ValueError(f"PromptPolicy template require cycle: {cycle}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"PromptPolicy template must be a mapping: {path}")
        schema = data.pop("schema", None)
        if schema not in (None, "tags-machine-core.prompt-policy-template/v1"):
            raise ValueError(f"Unsupported PromptPolicy template schema {schema!r}: {path}")
        name = str(data.pop("name", path.stem))
        parent_ref = data.pop("require", None)
        parent: dict[str, Any] = {}
        names: list[str] = []
        if parent_ref:
            parent, names = self._load_template_chain(
                str(parent_ref),
                relative_to=path.parent,
                stack=[*stack, path],
            )
        return deep_merge(parent, data), [*names, name]

    def _resolve_template_path(self, reference: str, *, relative_to: Path | None) -> Path:
        candidate = Path(reference)
        if candidate.suffix.lower() in {".yaml", ".yml"} or candidate.parent != Path("."):
            path = candidate if candidate.is_absolute() else (relative_to or Path.cwd()) / candidate
            path = path.resolve()
            if path.is_file():
                return path
            raise FileNotFoundError(f"PromptPolicy template not found: {path}")

        filename = f"{reference}.yaml"
        if self.template_root is not None:
            project_path = self.template_root / filename
            if project_path.is_file():
                return project_path.resolve()
        builtin_path = self.builtin_root / filename
        if builtin_path.is_file():
            return builtin_path.resolve()
        raise FileNotFoundError(f"PromptPolicy template not found: {reference}")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = {key: _copy_value(value) for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = _copy_value(value)
    return result


def _coerce_source(
    source: PromptPolicySource | dict[str, Any] | None,
) -> PromptPolicySource | None:
    if source is None or isinstance(source, PromptPolicySource):
        return source
    return PromptPolicySource.model_validate(source)


def _copy_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    return value


def _mapping_hash(mapping: dict[str, Any]) -> str:
    payload = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
