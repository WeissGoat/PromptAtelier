from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tags_machine_core.nodes.models import LegacyNodeMeta, NodeDocument
from tags_machine_core.nodes.novelai_artist import NovelAIArtistRepository

from .models import FileMutation, NodeEditorDocument, NodeEditorSource
from .text_utils import preserve_trailing_newline, read_text, source_hash


KNOWN_EXTENSION_KEYS = {
    "origin_uc",
    "uc",
    "after_uc",
    "gen_json",
    "gen_param",
}


class LegacyArtistTagsAdapter:
    adapter_id = "legacy_artist_tags/v1"

    def __init__(self, design_root: Path):
        self.design_root = Path(design_root).resolve()
        self.repository = NovelAIArtistRepository(self.design_root)

    def matches(self, node_dir: Path, role: str) -> bool:
        return role == "artist" and (node_dir / "tags.txt").exists()

    def read_editor(self, node_dir: Path) -> NodeEditorDocument:
        artist = self.repository.load(self._artist_ref(node_dir))
        tags_path = node_dir / "tags.txt"
        return NodeEditorDocument(
            adapter=self.adapter_id,
            role="artist",
            values={
                "name": node_dir.name,
                "prompt_prefix": artist.prompt_prefix,
                "prompt_suffix": artist.prompt_suffix,
                "negative_prompt": artist.negative_prompt,
                "after_negative_prompt": artist.after_negative_prompt,
                "params": artist.params,
                "flags": sorted(artist.flags),
            },
            sources=[
                NodeEditorSource(
                    path=str(tags_path.resolve()),
                    format="tags.txt",
                    sha256=source_hash(tags_path),
                )
            ],
            capabilities={"save": True, "multi_file": False},
        )

    def build_runtime_node(self, node_dir: Path, values: dict[str, Any]) -> NodeDocument:
        novelai = {
            "legacy_compat": True,
            "artist_ref": self._artist_ref(node_dir),
            "path": str(node_dir),
            "include_common_tags": False,
            "prompt_prefix": self._strings(values.get("prompt_prefix")),
            "prompt_suffix": self._strings(values.get("prompt_suffix")),
            "negative_prompt": self._strings(values.get("negative_prompt")),
            "after_negative_prompt": self._strings(values.get("after_negative_prompt")),
            "params": dict(values.get("params") or {}),
            "flags": self._strings(values.get("flags")),
        }
        return NodeDocument(
            schema="tags-machine.artist/v1",
            kind="artist",
            id=self._artist_ref(node_dir),
            name=str(values.get("name") or node_dir.name),
            path=node_dir,
            renderers={"novelai": novelai},
            legacy=LegacyNodeMeta(source_file=str(node_dir / "tags.txt")),
        )

    def preview_mutations(self, node_dir: Path, values: dict[str, Any]) -> list[FileMutation]:
        path = node_dir / "tags.txt"
        before = read_text(path)
        after = self._rewrite(before, values, node_dir)
        return [
            FileMutation(
                path=path,
                format="tags.txt",
                before_text=before,
                after_text=after,
                before_sha256=source_hash(path),
            )
        ]

    def _rewrite(self, source: str, values: dict[str, Any], node_dir: Path) -> str:
        lines = source.splitlines()
        prompt_lines: list[str] = []
        type_lines: list[str] = []
        extension_lines: list[str] = []
        in_extensions = False
        had_separator = False
        for line in lines:
            stripped = line.strip()
            if not in_extensions and stripped.startswith("="):
                in_extensions = True
                had_separator = True
                inline = stripped[1:].strip(" ,")
                if inline:
                    extension_lines.append(inline)
                continue
            if not in_extensions and stripped[:4] == "type":
                type_lines.append(line)
                continue
            if in_extensions:
                extension_lines.append(line)
            else:
                prompt_lines.append(line)

        original = self.repository.load(self._artist_ref(node_dir))
        original_prompt = [*original.prompt_prefix, *original.prompt_suffix]
        edited_prompt = [
            *self._strings(values.get("prompt_prefix")),
            *self._strings(values.get("prompt_suffix")),
        ]
        raw_prompt = [line for line in prompt_lines if line.strip()]
        next_prompt = [
            raw_prompt[index]
            if index < len(raw_prompt)
            and index < len(original_prompt)
            and value == original_prompt[index]
            else value
            for index, value in enumerate(edited_prompt)
        ]
        flags = self._strings(values.get("flags"))
        next_type = type_lines if sorted(flags) == sorted(original.flags) else ([f"type, {', '.join(flags)}"] if flags else [])

        negative = self._single_text(values.get("negative_prompt"))
        after_negative = self._single_text(values.get("after_negative_prompt"))
        params = dict(values.get("params") or {})
        replacements: dict[str, str | None] = {
            "origin_uc": f"origin_uc, {negative}" if negative else None,
            "uc": None,
            "after_uc": f"after_uc, {after_negative}" if after_negative else None,
            "gen_json": (
                None
                if not params
                else f"gen_json, {json.dumps(params, ensure_ascii=False, separators=(',', ':'))}"
            ),
            "gen_param": None,
        }
        if negative == original.negative_prompt:
            replacements["origin_uc"] = "__preserve__"
        if after_negative == original.after_negative_prompt:
            replacements["after_uc"] = "__preserve__"
        if params == original.params:
            replacements["gen_json"] = "__preserve__"

        emitted: set[str] = set()
        next_extensions: list[str] = []
        for line in extension_lines:
            key = line.split(",", 1)[0].strip()
            if key not in KNOWN_EXTENSION_KEYS:
                next_extensions.append(line)
                continue
            canonical = "origin_uc" if key == "uc" else "gen_json" if key == "gen_param" else key
            replacement = replacements.get(canonical)
            if replacement == "__preserve__":
                next_extensions.append(line)
                emitted.add(canonical)
                continue
            if canonical in emitted:
                continue
            emitted.add(canonical)
            if replacement:
                next_extensions.append(replacement)

        for key in ("origin_uc", "after_uc", "gen_json"):
            if key in emitted:
                continue
            replacement = replacements.get(key)
            if replacement and replacement != "__preserve__":
                next_extensions.append(replacement)

        result = [*next_prompt, *next_type]
        if had_separator or next_extensions:
            result.append("=")
            result.extend(next_extensions)
        return preserve_trailing_newline(source, result)

    def _artist_ref(self, node_dir: Path) -> str:
        try:
            return node_dir.resolve().relative_to(self.repository.artist_root.resolve()).as_posix()
        except ValueError:
            return str(node_dir.resolve())

    def _strings(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return [str(item) for item in value if str(item).strip()]

    def _single_text(self, value: Any) -> str:
        return ", ".join(self._strings(value))
