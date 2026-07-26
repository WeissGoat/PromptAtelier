from __future__ import annotations

import difflib
import uuid
from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.novelai_artist import NovelAIArtistRepository
from tags_machine_core.nodes.reader import NodeReader
from tags_machine_core.nodes.role_paths import role_roots
from tags_machine_core.web.node_editing import FileMutation, NodeSourceAdapterRegistry, create_default_registry
from tags_machine_core.web.node_editing.text_utils import source_hash
from tags_machine_core.web.services.node_save_preview_store import SourceChangedError


class NodeWorkspace:
    def __init__(
        self,
        *,
        design_root: str | Path,
        reader: NodeReader | None = None,
        adapter_registry: NodeSourceAdapterRegistry | None = None,
    ):
        self.design_root = Path(design_root).resolve()
        self.reader = reader or NodeReader()
        self.artist_repository = NovelAIArtistRepository(self.design_root)
        self.adapter_registry = adapter_registry or create_default_registry(self.design_root, self.reader)

    def list_nodes(
        self,
        role: str,
        query: str | None = None,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        nodes, _ = self.list_nodes_page(role, query=query, offset=0, limit=limit)
        return nodes

    def list_nodes_page(
        self,
        role: str,
        query: str | None = None,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], bool]:
        roots = role_roots(self.design_root, role)
        result: list[dict[str, Any]] = []
        needle = (query or "").strip().lower()
        offset = max(0, offset)
        limit = max(1, min(limit, 500))
        matched = 0
        for root in roots:
            if not root.exists():
                continue
            for item in self._iter_node_dirs(root):
                relative = item.relative_to(root).as_posix()
                searchable = f"{item.name} {relative}".lower()
                if needle and needle not in searchable:
                    continue
                if matched < offset:
                    matched += 1
                    continue
                if len(result) >= limit:
                    return result, True
                result.append(
                    {
                        "role": role,
                        "name": item.name,
                        "ref": str(item),
                        "relative": relative,
                    }
                )
        return result, False

    def read_node(self, ref: str | Path, *, role: str | None = None) -> dict[str, Any]:
        path = Path(ref).resolve()
        node = self.read_runtime_node(path, role=role)
        effective_role = role or node.kind
        editor = self.adapter_registry.resolve(path, effective_role).read_editor(path)
        return {
            "schema": "tags-machine-core.web.node/v2",
            "ref": str(path),
            "node": node.model_dump(mode="json"),
            "form": self.to_form(node),
            "raw": self._raw_file(path),
            "editor": editor.model_dump(mode="json"),
        }

    def read_runtime_node(self, ref: str | Path, *, role: str | None = None) -> NodeDocument:
        """读取生图链路使用的节点，不要求源文件具备 Web 编辑适配器。"""
        path = Path(ref).resolve()
        return self._read_node_document(path, role=role)

    def preview_editor(self, ref: str | Path, *, role: str, values: dict[str, Any]) -> dict[str, Any]:
        path = self.resolve_node_path(ref)
        adapter = self.adapter_registry.resolve(path, role)
        node = adapter.build_runtime_node(path, values)
        return {
            "schema": "tags-machine-core.web.node-editor-preview/v1",
            "node": node.model_dump(mode="json"),
            "editor": adapter.read_editor(path).model_dump(mode="json") | {"values": values},
        }

    def preview_file_mutations(
        self,
        ref: str | Path,
        *,
        role: str,
        values: dict[str, Any],
    ) -> tuple[NodeDocument, list[FileMutation]]:
        path = self.resolve_node_path(ref)
        adapter = self.adapter_registry.resolve(path, role)
        return adapter.build_runtime_node(path, values), adapter.preview_mutations(path, values)

    def mutation_payload(self, mutation: FileMutation, *, node_dir: str | Path) -> dict[str, Any]:
        relative = mutation.path.resolve().relative_to(Path(node_dir).resolve()).as_posix()
        diff = "".join(
            difflib.unified_diff(
                mutation.before_text.splitlines(keepends=True),
                mutation.after_text.splitlines(keepends=True),
                fromfile=relative,
                tofile=relative,
            )
        )
        return {
            "path": str(mutation.path.resolve()),
            "relative": relative,
            "format": mutation.format,
            "before_sha256": mutation.before_sha256,
            "changed": mutation.changed,
            "diff": diff,
            "after_text": mutation.after_text,
        }

    def commit_file_mutations(self, mutations: list[FileMutation]) -> None:
        changed = [mutation for mutation in mutations if mutation.changed]
        for mutation in changed:
            current_hash = source_hash(mutation.path)
            if current_hash != mutation.before_sha256:
                raise SourceChangedError(f"Source changed after preview: {mutation.path}")

        temporary: list[tuple[Path, Path]] = []
        try:
            for mutation in changed:
                mutation.path.parent.mkdir(parents=True, exist_ok=True)
                temp = mutation.path.with_name(f".{mutation.path.name}.{uuid.uuid4().hex}.promptatelier.tmp")
                temp.write_text(mutation.after_text, encoding="utf-8")
                temporary.append((temp, mutation.path))
            for temp, target in temporary:
                temp.replace(target)
        finally:
            for temp, _ in temporary:
                if temp.exists():
                    temp.unlink()

    def resolve_node_path(self, ref: str | Path) -> Path:
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = self.design_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.design_root)
        except ValueError as exc:
            raise ValueError("node path must be inside design_root") from exc
        return resolved

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

    def _read_node_document(self, path: Path, *, role: str | None) -> NodeDocument:
        if (
            role == "artist"
            and path.is_dir()
            and (path / "tags.txt").exists()
            and not any((path / name).exists() for name in ("meta.yaml", "node.yaml"))
        ):
            resolved = path.resolve()
            try:
                artist_ref = resolved.relative_to(self.artist_repository.artist_root.resolve()).as_posix()
            except ValueError:
                artist_ref = str(resolved)
            return self.artist_repository.load_node(artist_ref)
        return self.reader.read(path)

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
