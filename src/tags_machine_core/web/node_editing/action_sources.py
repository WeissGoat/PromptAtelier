from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.nodes.action_profile import load_action_profile
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.nodes.reader import NodeReader

from .models import FileMutation, NodeEditorDocument, NodeEditorSource
from .text_utils import preserve_trailing_newline, read_text, source_hash, split_prompt_tags


class ActionSourcesAdapter:
    adapter_id = "action_sources/v1"

    def __init__(self, reader: NodeReader | None = None):
        self.reader = reader or NodeReader()

    def matches(self, node_dir: Path, role: str) -> bool:
        return role == "action" and (node_dir / "tags.txt").exists()

    def read_editor(self, node_dir: Path) -> NodeEditorDocument:
        node = self.reader.read(node_dir)
        prompt_lines = self._prompt_lines(node_dir / "tags.txt")
        profile = load_action_profile(node_dir)
        selected_keys = []
        if profile:
            selected_keys = [entry.selected_keys for entry in profile.character_selection.characters]
        sources = [self._source(node_dir / "tags.txt", "tags.txt")]
        meta_path = node_dir / "meta.yaml"
        if meta_path.exists():
            sources.append(self._source(meta_path, "meta.yaml"))
        profile_path = self._profile_path(node_dir, profile.character_selection.source if profile else None)
        if profile_path:
            sources.append(self._source(profile_path, profile_path.name))
        return NodeEditorDocument(
            adapter=self.adapter_id,
            role="action",
            values={
                "id": node.id,
                "name": node.name,
                "description": node.description,
                "prompt_lines": prompt_lines,
                "negative": node.negative_prompt or node.negative_texts(),
                "selected_keys": selected_keys,
            },
            sources=sources,
            capabilities={"save": True, "multi_file": True},
        )

    def build_runtime_node(self, node_dir: Path, values: dict[str, Any]) -> NodeDocument:
        base = self.reader.read(node_dir)
        prompt_lines = self._strings(values.get("prompt_lines"))
        data = base.model_dump(mode="python")
        data.update(
            {
                "id": str(values.get("id") or base.id),
                "name": values.get("name"),
                "description": values.get("description"),
                "prompt": {"positive": prompt_lines},
                "negative_prompt": self._strings(values.get("negative")),
                "tags": {**base.tags, "action": split_prompt_tags(prompt_lines)},
            }
        )
        composition = dict(base.composition)
        selection = dict(composition.get("character_selection") or {})
        selection["characters"] = [
            {"selected_keys": self._strings(items)}
            for items in (values.get("selected_keys") or [])
        ]
        composition["character_selection"] = selection
        data["composition"] = composition
        return NodeDocument.model_validate(data)

    def preview_mutations(self, node_dir: Path, values: dict[str, Any]) -> list[FileMutation]:
        mutations = [self._tags_mutation(node_dir, values)]
        meta = self._meta_mutation(node_dir, values)
        if meta.changed:
            mutations.append(meta)
        profile = self._profile_mutation(node_dir, values)
        if profile and profile.changed:
            mutations.append(profile)
        return mutations

    def _tags_mutation(self, node_dir: Path, values: dict[str, Any]) -> FileMutation:
        path = node_dir / "tags.txt"
        before = read_text(path)
        lines = before.splitlines()
        suffix_start = len(lines)
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped[:4] == "type" or stripped.startswith("="):
                suffix_start = index
                break
        after_lines = [*self._strings(values.get("prompt_lines")), *lines[suffix_start:]]
        return FileMutation(
            path=path,
            format="tags.txt",
            before_text=before,
            after_text=preserve_trailing_newline(before, after_lines),
            before_sha256=source_hash(path),
        )

    def _meta_mutation(self, node_dir: Path, values: dict[str, Any]) -> FileMutation:
        path = node_dir / "meta.yaml"
        before = read_text(path)
        raw = yaml.safe_load(before) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Expected YAML mapping: {path}")
        prompt_lines = self._strings(values.get("prompt_lines"))
        raw.update(
            {
                "schema": raw.get("schema") or "tags-machine.action/v1",
                "kind": "action",
                "id": str(values.get("id") or node_dir.name),
                "name": values.get("name"),
                "description": values.get("description"),
                "tags": {**dict(raw.get("tags") or {}), "action": split_prompt_tags(prompt_lines)},
                "negative_prompt": self._strings(values.get("negative")),
            }
        )
        after = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
        return FileMutation(path=path, format="meta.yaml", before_text=before, after_text=after, before_sha256=source_hash(path))

    def _profile_mutation(self, node_dir: Path, values: dict[str, Any]) -> FileMutation | None:
        selected = [
            {"selected_keys": self._strings(items)}
            for items in (values.get("selected_keys") or [])
        ]
        profile = load_action_profile(node_dir)
        source = profile.character_selection.source if profile else None
        path = self._profile_path(node_dir, source)
        if path is None and not selected:
            return None
        path = path or (node_dir / "action_profile.yaml")
        before = read_text(path)
        if path.name == "run-prompt-prompt.md":
            after = self._rewrite_markdown_front_matter(before, selected)
        else:
            raw = yaml.safe_load(before) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"Expected YAML mapping: {path}")
            selection = dict(raw.get("character_selection") or {})
            selection["characters"] = selected
            raw["schema"] = raw.get("schema") or "tags-machine.action-profile/v1"
            raw["character_selection"] = selection
            after = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
        return FileMutation(path=path, format=path.name, before_text=before, after_text=after, before_sha256=source_hash(path))

    def _rewrite_markdown_front_matter(self, source: str, selected: list[dict[str, list[str]]]) -> str:
        lines = source.splitlines()
        if not lines or lines[0].strip() != "---":
            raw: dict[str, Any] = {"schema_version": 1, "characters": selected}
            front = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False).rstrip()
            return f"---\n{front}\n---\n\n{source}".rstrip() + "\n"
        end = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
        if end is None:
            raise ValueError("run-prompt-prompt.md front matter is not closed")
        raw = yaml.safe_load("\n".join(lines[1:end])) or {}
        if not isinstance(raw, dict):
            raise ValueError("run-prompt-prompt.md front matter must be a mapping")
        raw["characters"] = selected
        front = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False).rstrip()
        body = "\n".join(lines[end + 1 :])
        result = f"---\n{front}\n---\n{body}"
        return result + ("\n" if source.endswith(("\n", "\r")) else "")

    def _prompt_lines(self, path: Path) -> list[str]:
        lines: list[str] = []
        for line in read_text(path).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped[:4] == "type" or stripped.startswith("="):
                break
            lines.append(stripped)
        return lines

    def _profile_path(self, node_dir: Path, source: str | None) -> Path | None:
        if source:
            path = node_dir / source
            if path.exists():
                return path
        for name in ("action_profile.yaml", "run-prompt-prompt.md"):
            path = node_dir / name
            if path.exists():
                return path
        return None

    def _source(self, path: Path, format_name: str) -> NodeEditorSource:
        return NodeEditorSource(path=str(path.resolve()), format=format_name, sha256=source_hash(path))

    def _strings(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return [str(item) for item in value if str(item).strip()]
