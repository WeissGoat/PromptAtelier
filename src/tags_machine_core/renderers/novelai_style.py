from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


ARTIST_DIR_NAME = "\u753b\u98ce"


class NovelAIStyle(BaseModel):
    style_ref: str
    path: Path
    prompt_prefix: list[str] = Field(default_factory=list)
    prompt_suffix: list[str] = Field(default_factory=list)
    negative_prompt: str = ""
    after_negative_prompt: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    flags: set[str] = Field(default_factory=set)

    def style_payload(self) -> dict[str, Any]:
        return {
            "style_ref": self.style_ref,
            "path": str(self.path),
            "prompt_prefix": self.prompt_prefix,
            "prompt_suffix": self.prompt_suffix,
            "negative_prompt": self.negative_prompt,
            "after_negative_prompt": self.after_negative_prompt,
            "params": self.params,
            "flags": sorted(self.flags),
        }


class NovelAIStyleRepository:
    """只读旧项目的画风目录，不 import 旧项目代码。"""

    def __init__(self, design_root: str | Path):
        self.design_root = Path(design_root)
        self.artist_root = self.design_root / ARTIST_DIR_NAME

    def load(self, style_ref: str) -> NovelAIStyle:
        style_path = self._resolve_style_path(style_ref)
        tags_path = style_path / "tags.txt"
        if not tags_path.exists():
            raise FileNotFoundError(f"NovelAI style tags.txt not found: {tags_path}")
        return self._parse_tags_txt(style_ref=style_ref, style_path=style_path, tags_path=tags_path)

    def _resolve_style_path(self, style_ref: str) -> Path:
        path = Path(style_ref)
        if path.is_absolute():
            return path
        return self.artist_root / style_ref

    def _parse_tags_txt(self, style_ref: str, style_path: Path, tags_path: Path) -> NovelAIStyle:
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

        style = NovelAIStyle(
            style_ref=style_ref,
            path=style_path,
            prompt_prefix=prompt_prefix,
            prompt_suffix=prompt_suffix,
            flags=flags,
        )

        for line in ext_lines:
            key, value = self._split_ext_line(line)
            if not key:
                continue
            if key in {"origin_uc", "uc"}:
                style.negative_prompt = value
            elif key == "after_uc":
                style.after_negative_prompt = value
            elif key == "gen_json":
                style.params.update(self._parse_json_value(value, tags_path))
            elif key in {"not_quailty_prompts", "not_quality_prompts"}:
                style.flags.add(key)
            else:
                style.flags.add(key)

        return style

    def _is_type_line(self, line: str) -> bool:
        return line[:4] == "type"

    def _split_type_flags(self, line: str) -> set[str]:
        parts = [part.strip() for part in line.split(",") if part.strip()]
        return set(parts[1:])

    def _legacy_formula_prompt_parts(self, prompt_lines: list[str]) -> tuple[list[str], list[str]]:
        # 旧 run-prompt formula 使用 artist_lines[0] 作为前缀；如果第一行只有逗号，
        # join_prompt_parts 会把它清掉，所以完整 prompt 会排在画风正文前。
        if not prompt_lines:
            return [], []
        first = prompt_lines[0].strip(" ,")
        rest = [line.strip(" ,") for line in prompt_lines[1:]]
        return ([first] if first else []), [line for line in rest if line]

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
