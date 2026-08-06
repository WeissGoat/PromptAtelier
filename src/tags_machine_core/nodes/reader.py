from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .action_profile import load_action_profile
from .models import LegacyNodeMeta, NodeDocument

LEGACY_EXTENSION_PREFIXES = (
    "after_uc",
    "origin_uc",
    "origin_clear",
    "gen_json",
    "gen_param",
)


class NodeReader:
    """Read structured nodes without importing the legacy tags_machine code."""

    yaml_names = ("node.yaml", "meta.yaml")

    def read(self, path: str | Path) -> NodeDocument:
        path = Path(path)
        if path.is_file():
            if path.suffix.lower() in {".yaml", ".yml"}:
                return self._read_yaml(path)
            path = self._preferred_tags_path(path)
            return self._read_tags_txt(path)

        for name in self.yaml_names:
            candidate = path / name
            if candidate.exists():
                return self._read_yaml(candidate, node_dir=path)

        tags_txt = self._preferred_tags_path(path / "tags.txt")
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
        node = self._attach_legacy_tags_txt(node, node_dir)
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
        prompt_lines, type_lines, ext_lines = self._split_legacy_cnode_lines(lines)
        raw_sections: dict[str, list[str]] = {
            "prompt": prompt_lines,
        }
        if type_lines:
            raw_sections["type"] = type_lines
        if ext_lines:
            raw_sections["extension"] = ext_lines
        node = NodeDocument(
            kind="unknown",
            id=node_dir.name,
            name=node_dir.name,
            path=node_dir,
            tags={"legacy": prompt_lines},
            prompt={"positive": prompt_lines},
            legacy=LegacyNodeMeta(
                source_file=str(path),
                raw_lines=lines,
                raw_sections=raw_sections,
            ),
        )
        return self._attach_action_profile(node, node_dir)

    def _attach_legacy_tags_txt(self, node: NodeDocument, node_dir: Path) -> NodeDocument:
        tags_txt = self._preferred_tags_path(node_dir / "tags.txt")
        if not tags_txt.exists():
            return node
        lines = [
            line.strip()
            for line in tags_txt.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        prompt_lines, type_lines, ext_lines = self._split_legacy_cnode_lines(lines)
        raw_sections = dict(node.legacy.raw_sections)
        raw_sections.setdefault("prompt", prompt_lines)
        if type_lines:
            raw_sections.setdefault("type", type_lines)
        if ext_lines:
            raw_sections.setdefault("extension", ext_lines)
        legacy = node.legacy.model_copy(
            update={
                "source_file": node.legacy.source_file or str(tags_txt),
                "raw_lines": node.legacy.raw_lines or lines,
                "raw_sections": raw_sections,
            }
        )
        return node.model_copy(update={"legacy": legacy})

    def _preferred_tags_path(self, tags_txt: Path) -> Path:
        if tags_txt.name.lower() != "tags.txt":
            return tags_txt
        compiled = tags_txt.with_name("tags.compiled.txt")
        return compiled if compiled.is_file() else tags_txt

    def _attach_action_profile(self, node: NodeDocument, node_dir: Path) -> NodeDocument:
        profile = load_action_profile(node_dir)
        if profile is None:
            return node
        composition = dict(node.composition)
        composition.update(profile.to_node_composition())
        return node.model_copy(update={"composition": composition})

    def _split_legacy_cnode_lines(self, lines: list[str]) -> tuple[list[str], list[str], list[str]]:
        prompt_lines: list[str] = []
        type_lines: list[str] = []
        ext_lines: list[str] = []
        in_extension = False
        for line in lines:
            if in_extension:
                ext_lines.append(line)
                continue
            if line[:4] == "type":
                type_lines.append(line)
                continue
            stripped = line.strip()
            if stripped.startswith("="):
                in_extension = True
                inline_extension = stripped[1:].strip(" ,")
                if inline_extension:
                    ext_lines.append(inline_extension)
                continue
            if self._is_legacy_inline_extension(line):
                in_extension = True
                ext_lines.append(line)
                continue
            prompt_lines.append(line)
        return prompt_lines, type_lines, ext_lines

    def _is_legacy_inline_extension(self, line: str) -> bool:
        return any(marker in line for marker in LEGACY_EXTENSION_PREFIXES)

    def _as_string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if str(value).strip() else []
