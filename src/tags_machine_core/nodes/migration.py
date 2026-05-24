from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NEGATIVE_EXTENSION_KEYS = {
    "origin_uc",
    "uc",
    "negative_prompt",
    "after_uc",
    "after_negative_prompt",
}

LEGACY_PROMPT_DIRECTIVE_KEYS = {
    "type",
}


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


def migrate_legacy_character_tags(
    source: str | Path,
    *,
    node_id: str | None = None,
    name: str | None = None,
    character_id: str | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    """把旧角色 tags.txt 转成结构化 character meta，旧替换规则只归档不执行。"""
    tags_path = _resolve_tags_path(source)
    character_dir = tags_path.parent
    prompt_lines, ext_lines = _split_legacy_style_lines(tags_path)
    prompt_tags_by_line = [_split_top_level_commas(line) for line in prompt_lines]
    identity_tags = prompt_tags_by_line[0] if prompt_tags_by_line else []
    tags: dict[str, list[str]] = {}

    if identity_tags:
        tags["character"] = identity_tags[:1]
    if len(identity_tags) > 1:
        tags["copyright"] = identity_tags[1:]

    for line_tags in prompt_tags_by_line[1:]:
        for tag in line_tags:
            section = _classify_legacy_character_tag(tag)
            tags.setdefault(section, []).append(tag)

    result: dict[str, Any] = {
        "schema": "tags-machine.character/v1",
        "kind": "character",
        "id": node_id or character_dir.name,
        "name": name or character_dir.name,
        "character_id": character_id or (identity_tags[0] if identity_tags else character_dir.name),
        "description": "由旧角色 tags.txt 迁移生成。请人工复核 tags 分组；旧替换规则只保留在 legacy。",
        "tags": tags,
        "negative_prompt": _collect_legacy_negative_prompt(ext_lines),
        "legacy": {
            "source_file": str(tags_path),
            "raw_lines": prompt_lines + (["="] if ext_lines else []) + ext_lines,
            "raw_sections": {
                "prompt": prompt_lines,
                "extension": ext_lines,
            },
        },
        "agent": {
            "summary": "从旧 tags.txt 自动迁移的角色节点，只包含角色素材事实；旧替换规则没有提升为 v1 规则字段。",
            "labels": ["character", "migrated", "legacy_tags_txt", "needs_review"],
        },
    }
    if variant:
        result["variant"] = variant
    return result


def migrate_legacy_action_tags(
    source: str | Path,
    *,
    node_id: str | None = None,
    name: str | None = None,
    character_scope: str | None = None,
) -> dict[str, Any]:
    """把旧动作 tags.txt 转成结构化 action meta，不把规则写进节点。"""
    tags_path = _resolve_tags_path(source)
    action_dir = tags_path.parent
    prompt_lines, ext_lines = _split_legacy_style_lines(tags_path)
    action_tags = _split_legacy_prompt_tags(prompt_lines)
    resolved_scope = character_scope or _infer_action_character_scope(action_tags, tags_path)
    scope_source = "override" if character_scope else "inferred"

    return {
        "schema": "tags-machine.action/v1",
        "kind": "action",
        "id": node_id or action_dir.name,
        "name": name or action_dir.name,
        "description": "由旧动作 tags.txt 迁移生成。旧动作常混有角色、背景或画风词，请人工复核。",
        "tags": {"action": action_tags},
        "negative_prompt": _collect_legacy_negative_prompt(ext_lines),
        "character_scope": resolved_scope,
        "legacy": {
            "source_file": str(tags_path),
            "raw_lines": prompt_lines + (["="] if ext_lines else []) + ext_lines,
            "raw_sections": {
                "prompt": prompt_lines,
                "extension": ext_lines,
            },
        },
        "agent": {
            "summary": f"从旧 tags.txt 自动迁移的动作节点，character_scope={resolved_scope}（{scope_source}）。",
            "labels": [
                "action",
                "migrated",
                "legacy_tags_txt",
                "needs_review",
                resolved_scope,
                f"character_scope_{scope_source}",
            ],
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
        if key in NEGATIVE_EXTENSION_KEYS and value:
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
        raise FileNotFoundError(f"Legacy tags.txt not found: {path}")
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


def _collect_legacy_negative_prompt(ext_lines: list[str]) -> list[str]:
    negative_prompt: list[str] = []
    for line in ext_lines:
        key, value = _split_ext_line(line)
        if key in NEGATIVE_EXTENSION_KEYS and value:
            negative_prompt.append(value)
    return negative_prompt


def _split_legacy_prompt_tags(prompt_lines: list[str]) -> list[str]:
    tags: list[str] = []
    for line in prompt_lines:
        key, _ = _split_ext_line(line)
        if key in LEGACY_PROMPT_DIRECTIVE_KEYS:
            continue
        tags.extend(_split_top_level_commas(line))
    return tags


def _split_top_level_commas(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    stack: list[str] = []
    closing_to_opening = {")": "(", "]": "[", "}": "{"}
    for char in text:
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if stack and stack[-1] == closing_to_opening[char]:
                stack.pop()
        if char == "," and not stack:
            item = "".join(current).strip(" ,")
            if item:
                items.append(item)
            current = []
            continue
        current.append(char)
    item = "".join(current).strip(" ,")
    if item:
        items.append(item)
    return items


def _infer_action_character_scope(action_tags: list[str], source: Path) -> str:
    text = " ".join([*action_tags, *source.parts]).lower().replace("_", " ")

    def has_any(phrases: tuple[str, ...]) -> bool:
        return any(phrase in text for phrase in phrases)

    if has_any(
        (
            "foot focus",
            "feet focus",
            "toes focus",
            "foot close-up",
            "feet close-up",
            "shoes close-up",
            "soles",
            "sole ",
            "toes",
            "toenails",
            "foot in view",
            "st ft",
        )
    ):
        return "foot_detail"
    if has_any(
        (
            "hand focus",
            "hands focus",
            "hand close-up",
            "hands close-up",
            "close-up hands",
            "pov hands",
            "finger focus",
        )
    ):
        return "hand_detail"
    if has_any(
        (
            "face focus",
            "close-up face",
            "face close-up",
            "eye focus",
            "eyes focus",
            "mouth focus",
        )
    ):
        return "face_detail"
    if has_any(("portrait",)):
        return "portrait"
    if has_any(("upper body",)):
        return "upper_body"
    if has_any(("lower body", "thighs focus", "ass focus", "legs focus", "upper thigh")):
        return "lower_body"
    if has_any(("full body",)):
        return "full_body"
    return "default"


def _classify_legacy_character_tag(tag: str) -> str:
    normalized = tag.lower().strip().replace(" ", "_")
    if any(marker in normalized for marker in ("_hair", "hair_", "hairclip", "hairband", "ahoge")):
        if any(marker in normalized for marker in ("hairclip", "hairband", "hair_ornament", "hair_bow")):
            return "head_accessories"
        return "hair"
    if "_eyes" in normalized or normalized.endswith("_eye") or normalized in {"heterochromia"}:
        return "eyes"
    if any(marker in normalized for marker in ("mouth", "smile", "fang", "scar_across_eye")):
        return "face"
    if any(
        marker in normalized
        for marker in (
            "hat",
            "ribbon",
            "halo",
            "horn",
            "headdress",
            "headband",
            "hair_ornament",
            "hairclip",
            "hair_bow",
            "crown",
        )
    ):
        return "head_accessories"
    if "ear" in normalized:
        return "ears"
    if "tail" in normalized:
        return "tail"
    if "wing" in normalized:
        return "wings"
    if any(marker in normalized for marker in ("glove", "mitten", "handwear")):
        return "handwear"
    if any(
        marker in normalized
        for marker in (
            "thighhigh",
            "pantyhose",
            "socks",
            "kneehigh",
            "legwear",
            "stocking",
            "garter",
        )
    ):
        return "legwear"
    if any(
        marker in normalized
        for marker in (
            "shoe",
            "boot",
            "sneaker",
            "loafers",
            "high_heels",
            "mary_janes",
            "footwear",
        )
    ):
        return "footwear"
    if any(marker in normalized for marker in ("barefoot", "bare_feet", "feet", "toe", "soles")):
        return "feet"
    if any(marker in normalized for marker in ("sword", "gun", "shield", "weapon", "shirasaya", "wand")):
        return "weapons"
    if any(marker in normalized for marker in ("plush", "bag", "book", "umbrella", "instrument")):
        return "props"
    if any(
        marker in normalized
        for marker in (
            "dress",
            "kimono",
            "school_uniform",
            "uniform",
            "serafuku",
        )
    ):
        return "full_body_clothes"
    if any(marker in normalized for marker in ("skirt", "pants", "shorts", "bloomers")):
        return "lower_clothes"
    if any(
        marker in normalized
        for marker in (
            "blazer",
            "jacket",
            "shirt",
            "coat",
            "sweater",
            "hoodie",
            "sailor",
            "collar",
            "sleeves",
            "armor",
            "bra",
        )
    ):
        return "upper_clothes"
    if any(marker in normalized for marker in ("breasts", "skin", "navel", "body", "thighs")):
        return "body"
    if any(marker in normalized for marker in ("necklace", "choker", "belt", "logo", "badge")):
        return "accessories"
    return "unclassified"


def _parse_json_value(value: str, source: Path) -> dict[str, Any]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid gen_json in {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"gen_json must be a JSON object in {source}")
    return data
