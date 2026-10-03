from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync legacy character tags.txt cp relations into character meta.yaml."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default="../design/角色",
        help="Character root directory or a single character node directory.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write changes to meta.yaml. Without this flag the script only previews changes.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create meta.yaml.bak before writing when a backup does not already exist.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    candidates = _candidate_dirs(root)
    changed = 0
    skipped = 0

    for node_dir in candidates:
        tags_path = node_dir / "tags.txt"
        meta_path = node_dir / "meta.yaml"
        cp_refs = _read_cp_refs(tags_path)
        if not cp_refs:
            skipped += 1
            continue
        meta = _read_yaml(meta_path)
        if str(meta.get("kind") or "").strip() != "character":
            skipped += 1
            continue
        old_cp = _relation_values(meta, "cp")
        new_cp = _dedupe(old_cp + cp_refs)
        if new_cp == old_cp:
            skipped += 1
            continue
        changed += 1
        relative = _safe_relative(node_dir, root)
        print(f"[update] {relative}: cp {old_cp!r} -> {new_cp!r}")
        if args.write:
            if args.backup:
                backup_path = meta_path.with_name(meta_path.name + ".bak")
                if not backup_path.exists():
                    backup_path.write_text(meta_path.read_text(encoding="utf-8"), encoding="utf-8")
            _write_cp_relation_preserving_text(meta_path, new_cp)

    mode = "written" if args.write else "preview"
    print(f"[summary] mode={mode} candidates={len(candidates)} changed={changed} skipped={skipped}")
    return 0


def _candidate_dirs(root: Path) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(f"root not found: {root}")
    if (root / "tags.txt").exists() and (root / "meta.yaml").exists():
        return [root]
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_dir() and (path / "tags.txt").exists() and (path / "meta.yaml").exists()
    )


def _read_cp_refs(tags_path: Path) -> list[str]:
    refs: list[str] = []
    for raw_line in tags_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line == "=":
            if line == "=":
                break
            continue
        if not line.startswith("type"):
            continue
        for token in line.split(","):
            token = token.strip()
            if not token.startswith("cp|"):
                continue
            refs.extend(part.strip() for part in token.split("|")[1:] if part.strip())
    return _dedupe(refs)


def _read_yaml(meta_path: Path) -> dict[str, Any]:
    data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"meta.yaml must be a mapping: {meta_path}")
    return data


def _relation_values(meta: dict[str, Any], key: str) -> list[str]:
    relations = meta.get("relations")
    if not isinstance(relations, dict):
        return []
    value = relations.get(key)
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _write_cp_relation_preserving_text(meta_path: Path, cp_refs: list[str]) -> None:
    text = meta_path.read_text(encoding="utf-8")
    block = ["relations:", "  cp:"]
    block.extend(f"    - {ref}" for ref in cp_refs)
    relation_text = "\n".join(block) + "\n"

    if "\nrelations:" not in f"\n{text}":
        separator = "" if text.endswith("\n") else "\n"
        meta_path.write_text(text + separator + relation_text, encoding="utf-8")
        return

    data = _read_yaml(meta_path)
    relations = data.get("relations")
    if not isinstance(relations, dict):
        relations = {}
        data["relations"] = relations
    relations["cp"] = cp_refs
    meta_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
