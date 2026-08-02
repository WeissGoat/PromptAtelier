from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

KNOWLEDGE_BASE_SCHEMA = "tags-machine-core.knowledge-base/v1"


class KnowledgeBaseSourceConfig(BaseModel):
    id: str
    path: str | None = None
    pattern: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_source(self) -> KnowledgeBaseSourceConfig:
        self.id = self.id.strip()
        if not self.id:
            raise ValueError("knowledge base source id cannot be empty")
        if bool(self.path) == bool(self.pattern):
            raise ValueError(f"source {self.id!r} must define exactly one of path or pattern")
        return self


class ResolvedSourceRoot(BaseModel):
    root_id: str
    path: Path


class KnowledgeBaseConfig(BaseModel):
    schema_id: str = Field(alias="schema")
    action_root: Path
    catalog_dir: Path
    sources: list[KnowledgeBaseSourceConfig]
    config_path: Path

    @model_validator(mode="after")
    def validate_config(self) -> KnowledgeBaseConfig:
        if self.schema_id != KNOWLEDGE_BASE_SCHEMA:
            raise ValueError(
                f"unsupported knowledge base schema: {self.schema_id!r}; "
                f"expected {KNOWLEDGE_BASE_SCHEMA!r}"
            )
        ids = [source.id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("knowledge base source ids must be unique")
        if not self.action_root.is_dir():
            raise ValueError(f"action_root does not exist or is not a directory: {self.action_root}")
        return self

    def resolve_source_roots(
        self,
    ) -> tuple[list[ResolvedSourceRoot], list[tuple[str, str, str]]]:
        roots: list[ResolvedSourceRoot] = []
        issues: list[tuple[str, str, str]] = []
        seen: dict[Path, str] = {}
        for source in self.sources:
            if not source.enabled:
                continue
            candidates: list[Path]
            if source.path:
                candidates = [self.action_root / source.path]
            else:
                candidates = sorted(
                    (path for path in self.action_root.glob(source.pattern or "") if path.is_dir()),
                    key=lambda path: path.name.casefold(),
                )
                if not candidates:
                    issues.append((source.id, source.pattern or "", "source_missing"))
            for candidate in candidates:
                resolved = candidate.resolve()
                _ensure_within_root(resolved, self.action_root)
                if not resolved.is_dir():
                    relative = candidate.relative_to(self.action_root).as_posix()
                    issues.append((source.id, relative, "source_missing"))
                    continue
                if resolved in seen:
                    issues.append(
                        (
                            source.id,
                            resolved.relative_to(self.action_root).as_posix(),
                            "duplicate_source_match",
                        )
                    )
                    continue
                seen[resolved] = source.id
                roots.append(ResolvedSourceRoot(root_id=source.id, path=resolved))
        return roots, issues


def load_knowledge_base_config(path: str | Path) -> KnowledgeBaseConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"knowledge base config must be a YAML mapping: {config_path}")
    base_dir = config_path.parent
    action_root = _resolve_config_path(raw.get("action_root"), base_dir, "action_root")
    catalog_dir = _resolve_config_path(raw.get("catalog_dir"), base_dir, "catalog_dir")
    payload = dict(raw)
    payload.update(
        action_root=action_root,
        catalog_dir=catalog_dir,
        config_path=config_path,
    )
    return KnowledgeBaseConfig.model_validate(payload)


def _resolve_config_path(value: object, base_dir: Path, field_name: str) -> Path:
    if value is None or not str(value).strip():
        raise ValueError(f"knowledge base config requires {field_name}")
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _ensure_within_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"knowledge base source escapes action_root: {path}") from exc
