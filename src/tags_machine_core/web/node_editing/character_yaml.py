from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.reader import NodeReader

from .models import FileMutation, NodeEditorDocument, NodeEditorSource
from .text_utils import read_text, source_hash


RUNTIME_ONLY_KEYS = {"path", "renderers", "generation", "legacy"}


class CharacterMetaYamlAdapter:
    adapter_id = "character_meta_yaml/v1"

    def __init__(self, reader: NodeReader | None = None):
        self.reader = reader or NodeReader()

    def matches(self, node_dir: Path, role: str) -> bool:
        return role == "character" and (node_dir / "meta.yaml").exists()

    def read_editor(self, node_dir: Path) -> NodeEditorDocument:
        node = self.reader.read(node_dir)
        path = node_dir / "meta.yaml"
        return NodeEditorDocument(
            adapter=self.adapter_id,
            role="character",
            values={
                "id": node.id,
                "name": node.name,
                "description": node.description,
                "positive": node.positive_texts(),
                "negative": node.negative_prompt or node.negative_texts(),
                "identity_minimal": node.identity_minimal,
                "relations": node.relations,
                "tags": node.tags,
            },
            sources=[NodeEditorSource(path=str(path.resolve()), format="meta.yaml", sha256=source_hash(path))],
            capabilities={"save": True, "multi_file": False},
        )

    def build_runtime_node(self, node_dir: Path, values: dict[str, Any]) -> NodeDocument:
        base = self.reader.read(node_dir)
        data = base.model_dump(mode="python")
        data.update(
            {
                "id": str(values.get("id") or base.id),
                "name": values.get("name"),
                "description": values.get("description"),
                "prompt": {"positive": self._strings(values.get("positive"))},
                "negative_prompt": self._strings(values.get("negative")),
                "identity_minimal": self._strings(values.get("identity_minimal")),
                "relations": dict(values.get("relations") or {}),
                "tags": dict(values.get("tags") or {}),
            }
        )
        return NodeDocument.model_validate(data)

    def preview_mutations(self, node_dir: Path, values: dict[str, Any]) -> list[FileMutation]:
        path = node_dir / "meta.yaml"
        before = read_text(path)
        raw = yaml.safe_load(before) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Expected YAML mapping: {path}")
        for key in RUNTIME_ONLY_KEYS:
            raw.pop(key, None)
        raw.update(
            {
                "schema": raw.get("schema") or "tags-machine.character/v1",
                "kind": "character",
                "id": str(values.get("id") or node_dir.name),
                "name": values.get("name"),
                "description": values.get("description"),
                "negative_prompt": self._strings(values.get("negative")),
                "identity_minimal": self._strings(values.get("identity_minimal")),
                "relations": dict(values.get("relations") or {}),
                "tags": dict(values.get("tags") or {}),
            }
        )
        positive = self._strings(values.get("positive"))
        if positive:
            raw["prompt"] = {"positive": positive}
        else:
            raw.pop("prompt", None)
        raw = {key: value for key, value in raw.items() if value not in (None, [], {}) or key in {"schema", "kind", "id", "tags"}}
        after = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
        return [FileMutation(path=path, format="meta.yaml", before_text=before, after_text=after, before_sha256=source_hash(path))]

    def _strings(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return [str(item) for item in value if str(item).strip()]
