from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def migrate_legacy_style_tags(
    source: str | Path,
    *,
    node_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """把旧画风 tags.txt 转成结构化 style node，不依赖旧项目运行时代码。"""
    tags_path = _resolve_tags_path(source)
    style_dir = tags_path.parent
    prompt_lines, ext_lines = _split_legacy_style_lines(tags_path)
    cleaned_prompt_lines = [line.strip(" ,") for line in prompt_lines]
    cleaned_prompt_lines = [line for line in cleaned_prompt_lines if line]
    prompt_prefix = cleaned_prompt_lines[:1]
    prompt_suffix = cleaned_prompt_lines[1:]

    novelai: dict[str, Any] = {
        "include_common_tags": False,
        "prompt_prefix": prompt_prefix,
        "prompt_suffix": prompt_suffix,
        "params": {},
    }
    flags: list[str] = []
    legacy_extensions: dict[str, str] = {}

    for line in ext_lines:
        key, value = _split_ext_line(line)
        if not key:
            continue
        if key in {"origin_uc", "uc"}:
            if value:
                novelai["negative_prompt"] = [value]
        elif key == "after_uc":
            if value:
                novelai["after_negative_prompt"] = [value]
        elif key == "gen_json":
            novelai["params"].update(_parse_json_value(value, tags_path))
        elif key in {"not_quailty_prompts", "not_quality_prompts"}:
            flags.append(key)
        else:
            flags.append(key)
            if value:
                legacy_extensions[key] = value

    if flags:
        novelai["flags"] = sorted(set(flags))
    if legacy_extensions:
        novelai["legacy_extensions"] = legacy_extensions

    return {
        "schema": "tags-machine.style/v1",
        "kind": "style",
        "id": node_id or style_dir.name,
        "name": name or style_dir.name,
        "description": "由旧画风 tags.txt 迁移生成。请人工复核 tags 分组和跨后端配置。",
        "tags": {"style": cleaned_prompt_lines},
        "negative_prompt": [],
        "renderers": {"novelai": novelai},
        "legacy": {
            "source_file": str(tags_path),
            "raw_lines": prompt_lines + (["="] if ext_lines else []) + ext_lines,
            "raw_sections": {
                "prompt": prompt_lines,
                "extension": ext_lines,
            },
        },
        "agent": {
            "summary": "从旧 tags.txt 自动迁移的画风节点，后端行为优先保持 NovelAI 兼容。",
            "labels": ["style", "migrated", "legacy_tags_txt"],
        },
    }


def migrate_legacy_background_tags(
    source: str | Path,
    *,
    node_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """把旧背景 tags.txt 转成结构化 background meta，不依赖旧项目运行时代码。"""
    tags_path = _resolve_tags_path(source)
    background_dir = tags_path.parent
    prompt_lines, ext_lines = _split_legacy_style_lines(tags_path)
    cleaned_prompt_lines = [line.strip(" ,") for line in prompt_lines]
    cleaned_prompt_lines = [line for line in cleaned_prompt_lines if line]

    negative_prompt: list[str] = []
    for line in ext_lines:
        key, value = _split_ext_line(line)
        if key in {"origin_uc", "uc", "negative_prompt", "after_uc", "after_negative_prompt"} and value:
            negative_prompt.append(value)

    return {
        "schema": "tags-machine.background/v1",
        "kind": "background",
        "id": node_id or background_dir.name,
        "name": name or background_dir.name,
        "description": "由旧背景 tags.txt 迁移生成。请人工复核 tags 分组。",
        "tags": {"background": cleaned_prompt_lines},
        "negative_prompt": negative_prompt,
        "legacy": {
            "source_file": str(tags_path),
            "raw_lines": prompt_lines + (["="] if ext_lines else []) + ext_lines,
            "raw_sections": {
                "prompt": prompt_lines,
                "extension": ext_lines,
            },
        },
        "agent": {
            "summary": "从旧 tags.txt 自动迁移的背景节点，只包含场景素材和背景级负向词。",
            "labels": ["background", "migrated", "legacy_tags_txt"],
        },
    }


def _resolve_tags_path(source: str | Path) -> Path:
    path = Path(source)
    if path.is_dir():
        path = path / "tags.txt"
    if not path.exists():
        raise FileNotFoundError(f"Legacy style tags.txt not found: {path}")
    if path.name.lower() != "tags.txt":
        raise ValueError(f"Expected a tags.txt file or directory containing tags.txt: {path}")
    return path


def _split_legacy_style_lines(path: Path) -> tuple[list[str], list[str]]:
    raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    lines = [line.strip() for line in raw_lines if line.strip()]
    prompt_lines: list[str] = []
    ext_lines: list[str] = []
    in_ext = False
    for line in lines:
        if line == "=":
            in_ext = True
            continue
        if in_ext:
            ext_lines.append(line)
        else:
            prompt_lines.append(line)
    return prompt_lines, ext_lines


def _split_ext_line(line: str) -> tuple[str, str]:
    if "," not in line:
        return line.strip(), ""
    key, value = line.split(",", 1)
    return key.strip(), value.strip()


def _parse_json_value(value: str, source: Path) -> dict[str, Any]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid gen_json in {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"gen_json must be a JSON object in {source}")
    return data
