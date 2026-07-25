from __future__ import annotations

from pathlib import Path
from typing import Any

from tags_machine_core.config_fragments import load_required_mapping


class ProjectCollectionLoader:
    def __init__(self, require_paths: list[str], *, base_dir: str | Path):
        self.require_paths = list(require_paths)
        self.base_dir = Path(base_dir)

    def load(self) -> dict[str, dict[str, list[Any]]]:
        if not self.require_paths:
            return {}
        merged = load_required_mapping(
            {"require": self.require_paths},
            base_path=self.base_dir / ".promptatelier-web-project.yaml",
        )
        collections = merged.get("collections") or {}
        if not isinstance(collections, dict):
            raise ValueError("project collections must be a mapping")
        return collections
