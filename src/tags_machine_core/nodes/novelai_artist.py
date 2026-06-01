from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tags_machine_core.nodes.models import LegacyNodeMeta, NodeDocument


ARTIST_DIR_NAME = "\u753b\u98ce"


class NovelAIArtist(BaseModel):
    artist_ref: str
    path: Path
    prompt_prefix: list[str] = Field(default_factory=list)
    prompt_suffix: list[str] = Field(default_factory=list)
    negative_prompt: str = ""
    after_negative_prompt: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    flags: set[str] = Field(default_factory=set)

    def artist_payload(self) -> dict[str, Any]:
        return {
            "artist_ref": self.artist_ref,
            "path": str(self.path),
            "prompt_prefix": self.prompt_prefix,
            "prompt_suffix": self.prompt_suffix,
            "negative_prompt": self.negative_prompt,
            "after_negative_prompt": self.after_negative_prompt,
            "params": self.params,
            "flags": sorted(self.flags),
        }


class NovelAIArtistRepository:
    """读取旧 design/画风 节点，并把它归一化为 artist NodeDocument。"""

    def __init__(self, design_root: str | Path):
        self.design_root = Path(design_root)
        self.artist_root = self.design_root / ARTIST_DIR_NAME

    def load(self, artist_ref: str) -> NovelAIArtist:
        artist_path = self._resolve_artist_path(artist_ref)
        tags_path = artist_path / "tags.txt"
        if not tags_path.exists():
            raise FileNotFoundError(f"NovelAI artist tags.txt not found: {tags_path}")
        return self._parse_tags_txt(artist_ref=artist_ref, artist_path=artist_path, tags_path=tags_path)

    def load_node(self, artist_ref: str) -> NodeDocument:
        artist = self.load(artist_ref)
        novelai: dict[str, Any] = {
            "legacy_compat": True,
            "artist_ref": artist.artist_ref,
            "path": str(artist.path),
            "include_common_tags": False,
            "prompt_prefix": artist.prompt_prefix,
            "prompt_suffix": artist.prompt_suffix,
            "negative_prompt": [artist.negative_prompt] if artist.negative_prompt else [],
            "after_negative_prompt": (
                [artist.after_negative_prompt] if artist.after_negative_prompt else []
            ),
            "params": artist.params,
            "flags": sorted(artist.flags),
        }
        return NodeDocument(
            schema="tags-machine.artist/v1",
            kind="artist",
            id=artist.artist_ref,
            name=Path(artist.artist_ref).name,
            path=artist.path,
            renderers={"novelai": novelai},
            legacy=LegacyNodeMeta(source_file=str(artist.path / "tags.txt")),
        )

    def _resolve_artist_path(self, artist_ref: str) -> Path:
        path = Path(artist_ref)
        if path.is_absolute():
            return path
        return self.artist_root / artist_ref

    def _parse_tags_txt(self, artist_ref: str, artist_path: Path, tags_path: Path) -> NovelAIArtist:
        raw_lines = tags_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        lines = [line.strip() for line in raw_lines if line.strip()]

        prompt_lines: list[str] = []
        ext_lines: list[str] = []
        flags: set[str] = set()
        in_ext = False
        for line in lines:
            if line == "=":
                in_ext = True
                continue
            if in_ext:
                ext_lines.append(line)
            elif self._is_type_line(line):
                flags.update(self._split_type_flags(line))
            else:
                prompt_lines.append(line)

        prompt_prefix, prompt_suffix = self._legacy_formula_prompt_parts(prompt_lines)

        artist = NovelAIArtist(
            artist_ref=artist_ref,
            path=artist_path,
            prompt_prefix=prompt_prefix,
            prompt_suffix=prompt_suffix,
            flags=flags,
        )

        for line in ext_lines:
            key, value = self._split_ext_line(line)
            if not key:
                continue
            if key in {"origin_uc", "uc"}:
                artist.negative_prompt = value
            elif key == "after_uc":
                artist.after_negative_prompt = value
            elif key == "gen_json":
                artist.params.update(self._parse_json_value(value, tags_path))
            elif key in {"not_quailty_prompts", "not_quality_prompts"}:
                artist.flags.add(key)
            else:
                artist.flags.add(key)

        return artist

    def _is_type_line(self, line: str) -> bool:
        return line[:4] == "type"

    def _split_type_flags(self, line: str) -> set[str]:
        parts = [part.strip() for part in line.split(",") if part.strip()]
        return set(parts[1:])

    def _legacy_formula_prompt_parts(self, prompt_lines: list[str]) -> tuple[list[str], list[str]]:
        # 旧 formula 约等于 line A + character + line B + action + line C。
        # 新 run-prompt 的角色和动作已经合成完整 prompt，因此把前两段画风放到 prompt 前。
        if not prompt_lines:
            return [], []
        prefix = [line.strip(" ,") for line in prompt_lines[:2]]
        suffix = [line.strip(" ,") for line in prompt_lines[2:]]
        return [line for line in prefix if line], [line for line in suffix if line]

    def _split_ext_line(self, line: str) -> tuple[str, str]:
        if "," not in line:
            return line.strip(), ""
        key, value = line.split(",", 1)
        return key.strip(), value.strip()

    def _parse_json_value(self, value: str, source: Path) -> dict[str, Any]:
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid gen_json in {source}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"gen_json must be a JSON object in {source}")
        return data
