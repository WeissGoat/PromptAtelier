from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .action_profile import load_action_profile
from .models import LegacyNodeMeta, NodeDocument


class NodeReader:
    """Read structured nodes without importing the legacy tags_machine code."""

    yaml_names = ("node.yaml", "meta.yaml")

    def read(self, path: str | Path) -> NodeDocument:
        path = Path(path)
        if path.is_file():
            if path.suffix.lower() in {".yaml", ".yml"}:
                return self._read_yaml(path)
            return self._read_tags_txt(path)

        for name in self.yaml_names:
            candidate = path / name
            if candidate.exists():
                return self._read_yaml(candidate, node_dir=path)

        tags_txt = path / "tags.txt"
        if tags_txt.exists():
            return self._read_tags_txt(tags_txt, node_dir=path)

        raise FileNotFoundError(f"No node.yaml, meta.yaml, or tags.txt found under {path}")

    def _read_yaml(self, path: Path, node_dir: Path | None = None) -> NodeDocument:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Expected YAML mapping: {path}")

        node_dir = node_dir or path.parent
        data = self._normalize_yaml_data(data)
        data.setdefault("id", node_dir.name)
        data.setdefault("path", node_dir)
        node = NodeDocument.model_validate(data)
        return self._attach_action_profile(node, node_dir)

    def _normalize_yaml_data(self, data: dict[str, Any]) -> dict[str, Any]:
        tags = data.get("tags") or {}
        if isinstance(tags, list):
            data["tags"] = {"default": [str(item) for item in tags]}
        elif isinstance(tags, dict):
            data["tags"] = {
                str(key): self._as_string_list(value) for key, value in tags.items()
            }
        prompt = data.get("prompt")
        if isinstance(prompt, (str, list)):
            data["prompt"] = {"positive": prompt}
        return data

    def _read_tags_txt(self, path: Path, node_dir: Path | None = None) -> NodeDocument:
        node_dir = node_dir or path.parent
        lines = [
            line.strip()
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        node = NodeDocument(
            kind="unknown",
            id=node_dir.name,
            name=node_dir.name,
            path=node_dir,
            tags={"legacy": lines},
            prompt={"positive": lines},
            legacy=LegacyNodeMeta(source_file=str(path), raw_lines=lines),
        )
        return self._attach_action_profile(node, node_dir)

    def _attach_action_profile(self, node: NodeDocument, node_dir: Path) -> NodeDocument:
        profile = load_action_profile(node_dir)
        if profile is None:
            return node
        composition = dict(node.composition)
        composition.update(profile.to_node_composition())
        return node.model_copy(update={"composition": composition})

    def _as_string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if str(value).strip() else []
