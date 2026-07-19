from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def source_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def preserve_trailing_newline(source: str, lines: list[str]) -> str:
    text = "\n".join(lines)
    if source.endswith(("\n", "\r")) and text:
        return text + "\n"
    return text


def split_prompt_tags(lines: list[str]) -> list[str]:
    tags: list[str] = []
    for line in lines:
        tags.extend(item.strip() for item in line.split(",") if item.strip())
    return tags
