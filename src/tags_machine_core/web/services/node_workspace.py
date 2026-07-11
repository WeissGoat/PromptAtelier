from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.reader import NodeReader


ROLE_DIRS = {
    "artist": ["画风", "artist", "artists"],
    "character": ["角色", "character", "characters"],
    "action": ["动作改2", "动作", "action", "actions"],
    "background": ["背景", "background", "backgrounds"],
}


class NodeWorkspace:
    def __init__(self, *, design_root: str | Path, reader: NodeReader | None = None):
        self.design_root = Path(design_root).resolve()
        self.reader = reader or NodeReader()

    def list_nodes(
        self,
        role: str,
        query: str | None = None,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        roots = [self.design_root / item for item in ROLE_DIRS.get(role, [role])]
        result: list[dict[str, Any]] = []
        needle = (query or "").strip().lower()
        limit = max(1, min(limit, 500))
        for root in roots:
            if not root.exists():
                continue
            for item in self._iter_node_dirs(root):
                relative = item.relative_to(root).as_posix()
                searchable = f"{item.name} {relative}".lower()
                if needle and needle not in searchable:
                    continue
                result.append(
                    {
                        "role": role,
                        "name": item.name,
                        "ref": str(item),
                        "relative": relative,
                    }
                )
                if len(result) >= limit:
                    return result
        return result

    def read_node(self, ref: str | Path) -> dict[str, Any]:
        path = Path(ref)
        node = self.reader.read(path)
        return {
            "schema": "tags-machine-core.web.node/v1",
            "ref": str(path),
            "node": node.model_dump(mode="json"),
            "form": self.to_form(node),
            "raw": self._raw_file(path),
        }

    def preview_node(self, raw: dict[str, Any]) -> dict[str, Any]:
        node = NodeDocument.model_validate(raw)
        return {
            "schema": "tags-machine-core.web.node-preview/v1",
            "node": node.model_dump(mode="json"),
            "form": self.to_form(node),
        }

    def save_node(self, ref: str | Path, node_data: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_save_path(ref)
        node = NodeDocument.model_validate(node_data)
        path.mkdir(parents=True, exist_ok=True)
        target = path / "meta.yaml"
        target.write_text(
            yaml.safe_dump(node.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return self.read_node(path)

    def _resolve_save_path(self, ref: str | Path) -> Path:
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = self.design_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.design_root)
        except ValueError as exc:
            raise ValueError("node save target must be inside design_root") from exc
        return resolved

    def to_form(self, node: NodeDocument) -> dict[str, Any]:
        return {
            "kind": node.kind,
            "id": node.id,
            "name": node.name,
            "description": node.description,
            "prompt": {
                "positive": [fragment.text for fragment in node.prompt.positive],
                "negative": [fragment.text for fragment in node.prompt.negative],
            },
            "tags": node.tags,
            "relations": node.relations,
            "composition": node.composition,
        }

    def _has_node_file(self, path: Path) -> bool:
        return any((path / name).exists() for name in ("meta.yaml", "node.yaml", "tags.txt"))

    def _iter_node_dirs(self, root: Path):
        stack = [root]
        while stack:
            current = stack.pop()
            if current != root and self._has_node_file(current):
                yield current
                continue
            try:
                children = sorted(
                    [item for item in current.iterdir() if item.is_dir()],
                    key=lambda path: path.name,
                    reverse=True,
                )
            except OSError:
                continue
            stack.extend(children)

    def _raw_file(self, path: Path) -> dict[str, str] | None:
        for name in ("meta.yaml", "node.yaml", "tags.txt"):
            candidate = path / name
            if candidate.exists():
                return {
                    "filename": name,
                    "text": candidate.read_text(encoding="utf-8", errors="ignore"),
                }
        return None
