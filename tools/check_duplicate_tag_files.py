#!/usr/bin/env python3
"""扫描目录中的 tags.txt，并警告标签集合内容重复的文件。"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


CONTROL_KEYS = {
    "after_negative_prompt",
    "after_uc",
    "extension",
    "gen_json",
    "gen_param",
    "negative_prompt",
    "origin_clear",
    "origin_uc",
    "type",
    "uc",
}

TagSignature = tuple[tuple[str, ...], tuple[str, ...]]


@dataclass(frozen=True)
class ScanError:
    path: Path
    message: str


@dataclass(frozen=True)
class DuplicateGroup:
    signature: TagSignature
    paths: tuple[Path, ...]

    @property
    def tags(self) -> tuple[str, ...]:
        return self.signature[0]

    @property
    def control_lines(self) -> tuple[str, ...]:
        return self.signature[1]

    @property
    def folder_count(self) -> int:
        return len({path.parent for path in self.paths})


@dataclass(frozen=True)
class ScanResult:
    root: Path
    scanned: int
    duplicate_groups: tuple[DuplicateGroup, ...]
    errors: tuple[ScanError, ...]

    @property
    def duplicate_files(self) -> int:
        return sum(len(group.paths) for group in self.duplicate_groups)


def scan_tag_files(root: Path) -> ScanResult:
    """递归扫描 root 下的 tags.txt，并按规范化内容分组。"""
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"root must be a directory: {root}")

    paths = sorted(
        (path for path in root.rglob("tags.txt") if path.is_file()),
        key=lambda path: _relative_sort_key(path, root),
    )
    grouped: dict[TagSignature, list[Path]] = defaultdict(list)
    errors: list[ScanError] = []

    for path in paths:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            errors.append(ScanError(path=path, message=str(exc)))
            continue
        grouped[_build_signature(text)].append(path)

    duplicate_groups = [
        DuplicateGroup(signature=signature, paths=tuple(paths))
        for signature, paths in grouped.items()
        if len(paths) >= 2
    ]
    duplicate_groups.sort(key=lambda group: _relative_sort_key(group.paths[0], root))
    return ScanResult(
        root=root,
        scanned=len(paths),
        duplicate_groups=tuple(duplicate_groups),
        errors=tuple(errors),
    )


def _build_signature(text: str) -> TagSignature:
    tags: set[str] = set()
    control_lines: set[str] = set()
    in_control_block = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("="):
            in_control_block = True
            normalized = _normalize_control_line(line)
            if normalized:
                control_lines.add(normalized)
            continue

        if in_control_block or _is_control_line(line):
            normalized = _normalize_control_line(line)
            if normalized:
                control_lines.add(normalized)
            continue

        for value in _split_top_level_commas(line):
            normalized = _normalize_tag(value)
            if normalized:
                tags.add(normalized)

    return tuple(sorted(tags)), tuple(sorted(control_lines))


def _is_control_line(line: str) -> bool:
    key = line.split(",", 1)[0].strip().lower()
    return key in CONTROL_KEYS


def _normalize_tag(value: str) -> str:
    normalized = re.sub(r"\s+", "_", value.strip().lower())
    return re.sub(r"_+", "_", normalized)


def _normalize_control_line(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    normalized = re.sub(r"\s*,\s*", ",", normalized)
    return re.sub(r"\s*=\s*", "=", normalized, count=1)


def _split_top_level_commas(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    stack: list[str] = []
    closing_to_opening = {")": "(", "]": "[", "}": "{"}

    for character in text:
        if character in "([{":
            stack.append(character)
        elif character in ")]}" and stack and stack[-1] == closing_to_opening[character]:
            stack.pop()

        if character == "," and not stack:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
            continue
        current.append(character)

    item = "".join(current).strip()
    if item:
        items.append(item)
    return items


def _relative_sort_key(path: Path, root: Path) -> tuple[str, str]:
    relative = path.relative_to(root).as_posix()
    return relative.casefold(), relative


def _display_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="递归扫描 tags.txt，并警告标签集合内容重复的文件。"
    )
    parser.add_argument("root", help="需要扫描的根目录")
    args = parser.parse_args(argv)

    try:
        result = scan_tag_files(Path(args.root))
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    for error in result.errors:
        print(
            f"ERROR failed to read {_display_path(error.path, result.root)}: "
            f"{error.message}",
            file=sys.stderr,
        )

    for index, group in enumerate(result.duplicate_groups, start=1):
        print(
            f"WARNING duplicate tags content group={index} "
            f"(files={len(group.paths)}, folders={group.folder_count}):",
            file=sys.stderr,
        )
        print(
            "  normalized_tags: "
            f"{', '.join(group.tags) if group.tags else '(empty)'}",
            file=sys.stderr,
        )
        print(
            "  control_lines: "
            f"{'; '.join(group.control_lines) if group.control_lines else '(none)'}",
            file=sys.stderr,
        )
        for path in group.paths:
            folder = path.parent.relative_to(result.root).as_posix() or "."
            print(f"  folder: {folder}", file=sys.stderr)
            print(f"  tags_file: {_display_path(path, result.root)}", file=sys.stderr)

    print(
        f"scanned={result.scanned} "
        f"duplicate_groups={len(result.duplicate_groups)} "
        f"duplicate_files={result.duplicate_files} "
        f"errors={len(result.errors)}"
    )
    print(
        "说明: duplicate_groups=重复内容组数量；"
        "duplicate_files=参与重复的 tags.txt 文件总数"
    )
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
