from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from .migration import migrate_legacy_action_tags


VALID_CLOTHING_STATES = {"nude", "clothed", "specific_outfit"}
NO_DRESS_TOKENS = {"no dress", "no_dress", "nodress"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan action classify.yaml/tags.txt and fill action meta.yaml clothing facts."
    )
    parser.add_argument(
        "root",
        help="Action root directory or a single action node directory.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write meta.yaml changes. Without this flag only a report is produced.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create meta.yaml.bak before overwriting an existing meta.yaml.",
    )
    parser.add_argument(
        "--report",
        help="Write a JSON report to this path.",
    )
    args = parser.parse_args()

    result = fill_action_meta_clothing(
        root=Path(args.root),
        write=args.write,
        backup=args.backup,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(text)
    return 0 if not result["summary"]["errors"] else 1


def fill_action_meta_clothing(
    root: Path,
    *,
    write: bool = False,
    backup: bool = False,
    ensure_meta: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    items: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "mode": "write" if write else "preview",
        "root": str(root),
        "ensure_meta": ensure_meta,
        "scanned": 0,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "errors": 0,
        "state_counts": {},
        "action_outfit_counts": {},
        "type_counts": {},
        "conflict_counts": {},
    }
    state_counts: Counter[str] = Counter()
    outfit_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    conflict_counts: Counter[str] = Counter()

    for node_dir in _candidate_dirs(root):
        summary["scanned"] += 1
        try:
            item = _process_node(
                node_dir,
                root=root,
                write=write,
                backup=backup,
                ensure_meta=ensure_meta,
            )
        except Exception as exc:  # noqa: BLE001 - 脚本需要继续扫描并在报告里标记坏节点。
            summary["errors"] += 1
            item = {
                "node_dir": str(node_dir),
                "relative": _safe_relative(node_dir, root),
                "status": "error",
                "error": str(exc),
            }
        items.append(item)

        status = item.get("status")
        if status == "created":
            summary["created"] += 1
        elif status == "updated":
            summary["updated"] += 1
        elif status == "unchanged":
            summary["unchanged"] += 1
        elif status == "skipped":
            summary["skipped"] += 1

        clothing = item.get("clothing")
        if isinstance(clothing, dict):
            state = clothing.get("state")
            if state:
                state_counts[str(state)] += 1
            outfit_counts[str(bool(clothing.get("action_outfit"))).lower()] += 1
            source = clothing.get("source")
            if isinstance(source, dict):
                for key in ("type_dress", "type_no_dress"):
                    if source.get(key):
                        type_counts[key] += 1
        for conflict in item.get("conflicts") or []:
            conflict_counts[str(conflict)] += 1

    summary["state_counts"] = dict(sorted(state_counts.items()))
    summary["action_outfit_counts"] = dict(sorted(outfit_counts.items()))
    summary["type_counts"] = dict(sorted(type_counts.items()))
    summary["conflict_counts"] = dict(sorted(conflict_counts.items()))
    return {
        "schema": "tags-machine-core.action-clothing-fill-report/v1",
        "summary": summary,
        "items": items,
    }


def _process_node(
    node_dir: Path,
    *,
    root: Path,
    write: bool,
    backup: bool,
    ensure_meta: bool,
) -> dict[str, Any]:
    classify_path = node_dir / "classify.yaml"
    tags_path = node_dir / "tags.txt"
    meta_path = node_dir / "meta.yaml"
    source_signatures = {
        classify_path: _file_signature(classify_path),
        tags_path: _file_signature(tags_path),
        meta_path: _file_signature(meta_path),
    }

    classify = _read_yaml_mapping(classify_path) if classify_path.exists() else {}
    state, state_warning = _read_clothing_state(classify)
    type_info = _read_type_info(tags_path) if tags_path.exists() else _empty_type_info()
    clothing = _build_clothing(state=state, type_info=type_info)
    conflicts = _detect_conflicts(state=state, type_info=type_info)

    if state_warning:
        conflicts.append(state_warning)

    has_clothing_signals = bool(
        state or type_info["type_dress"] or type_info["type_no_dress"]
    )
    if not has_clothing_signals and not ensure_meta:
        return {
            "node_dir": str(node_dir),
            "relative": _safe_relative(node_dir, root),
            "status": "skipped",
            "reason": "no clothing signals",
        }

    existed = meta_path.exists()
    if ensure_meta and not existed and not tags_path.exists():
        raise FileNotFoundError(f"missing tags.txt for new action node: {node_dir}")

    meta = _load_or_create_meta(node_dir, meta_path=meta_path, tags_path=tags_path)
    meta_changed = False
    if has_clothing_signals:
        meta_changed = _clean_legacy_type_sections(meta)
        if meta.get("clothing") != clothing:
            meta["clothing"] = clothing
            meta_changed = True

    if not existed:
        status = "created"
    elif meta_changed:
        status = "updated"
    else:
        status = "unchanged"

    should_write = write and status in {"created", "updated"}
    if should_write:
        if backup and existed:
            backup_path = meta_path.with_name(meta_path.name + ".bak")
            if not backup_path.exists():
                backup_path.write_text(meta_path.read_text(encoding="utf-8"), encoding="utf-8")
        _write_yaml(meta_path, meta, expected_signatures=source_signatures)

    item = {
        "node_dir": str(node_dir),
        "relative": _safe_relative(node_dir, root),
        "status": status,
        "meta_path": str(meta_path),
        "conflicts": conflicts,
        "write": should_write,
    }
    if has_clothing_signals:
        item["clothing"] = clothing
    return item


def _candidate_dirs(root: Path) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(f"root not found: {root}")
    if root.is_file():
        raise ValueError(f"root must be a directory: {root}")
    if (root / "classify.yaml").exists() or (root / "tags.txt").exists() or (root / "meta.yaml").exists():
        return [root]
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_dir()
        and ((path / "classify.yaml").exists() or (path / "tags.txt").exists())
    )


def _load_or_create_meta(node_dir: Path, *, meta_path: Path, tags_path: Path) -> dict[str, Any]:
    if meta_path.exists():
        data = _read_yaml_mapping(meta_path)
        data.setdefault("schema", "tags-machine.action/v1")
        data.setdefault("kind", "action")
        data.setdefault("id", node_dir.name)
        return data
    if tags_path.exists():
        return migrate_legacy_action_tags(tags_path, node_id=node_dir.name, name=node_dir.name)
    return {
        "schema": "tags-machine.action/v1",
        "kind": "action",
        "id": node_dir.name,
        "name": node_dir.name,
        "description": "由 classify.yaml 自动创建的动作节点，请人工补充 tags.action。",
        "tags": {"action": []},
        "negative_prompt": [],
        "character_scope": "default",
        "legacy": {
            "source_file": str(node_dir),
            "raw_lines": [],
            "raw_sections": {},
        },
        "agent": {
            "summary": "由 classify.yaml 自动创建的动作节点，缺少 tags.txt，请人工复核。",
            "labels": ["action", "migrated", "needs_review"],
        },
    }


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML mapping: {path}")
    return data


def _read_clothing_state(classify: dict[str, Any]) -> tuple[str | None, str | None]:
    raw_state = classify.get("clothing")
    if raw_state is None:
        return None, None
    state = str(raw_state).strip()
    if not state:
        return None, None
    if state not in VALID_CLOTHING_STATES:
        return None, f"invalid_clothing_state:{state}"
    return state, None


def _read_type_info(tags_path: Path) -> dict[str, Any]:
    type_lines: list[str] = []
    type_tokens: list[str] = []
    type_dress = False
    type_no_dress = False

    for raw_line in tags_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("type"):
            continue
        type_lines.append(line)
        for raw_token in line.split(",")[1:]:
            token = raw_token.strip()
            normalized = token.lower().replace("_", " ")
            if not token:
                continue
            type_tokens.append(token)
            if normalized == "dress":
                type_dress = True
            if normalized in NO_DRESS_TOKENS:
                type_no_dress = True

    return {
        "type_lines": type_lines,
        "type_tokens": _dedupe(type_tokens),
        "type_dress": type_dress,
        "type_no_dress": type_no_dress,
    }


def _empty_type_info() -> dict[str, Any]:
    return {
        "type_lines": [],
        "type_tokens": [],
        "type_dress": False,
        "type_no_dress": False,
    }


def _build_clothing(*, state: str | None, type_info: dict[str, Any]) -> dict[str, Any]:
    type_no_dress = bool(type_info["type_no_dress"])
    type_dress = bool(type_info["type_dress"])
    action_outfit = (state == "specific_outfit" or type_dress) and not type_no_dress
    return {
        "state": state,
        "action_outfit": action_outfit,
        "source": {
            "classify": "classify.yaml" if state else None,
            "type_dress": type_dress,
            "type_no_dress": type_no_dress,
            "type_tokens": type_info["type_tokens"],
        },
    }


def _clean_legacy_type_sections(meta: dict[str, Any]) -> bool:
    changed = False
    legacy = meta.get("legacy")
    if not isinstance(legacy, dict):
        return False
    raw_sections = legacy.get("raw_sections")
    if not isinstance(raw_sections, dict):
        return False

    prompt_lines = raw_sections.get("prompt")
    if isinstance(prompt_lines, list):
        kept_prompt: list[Any] = []
        type_lines: list[str] = []
        for line in prompt_lines:
            text = str(line).strip()
            if text[:4] == "type":
                type_lines.append(text)
                changed = True
            else:
                kept_prompt.append(line)
        if changed:
            raw_sections["prompt"] = kept_prompt
            raw_sections["type"] = _dedupe(_as_string_list(raw_sections.get("type")) + type_lines)

    tags = meta.get("tags")
    if isinstance(tags, dict):
        action_tags = tags.get("action")
        if isinstance(action_tags, list):
            cleaned_tags = [tag for tag in action_tags if not str(tag).strip()[:4] == "type"]
            if cleaned_tags != action_tags:
                tags["action"] = cleaned_tags
                changed = True
        elif isinstance(action_tags, str) and action_tags.strip()[:4] == "type":
            tags["action"] = []
            changed = True
    return changed


def _detect_conflicts(*, state: str | None, type_info: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    if state == "nude" and type_info["type_dress"]:
        conflicts.append("nude_with_type_dress")
    if state == "specific_outfit" and type_info["type_no_dress"]:
        conflicts.append("specific_outfit_with_type_no_dress")
    if type_info["type_dress"] and type_info["type_no_dress"]:
        conflicts.append("type_dress_and_type_no_dress")
    return conflicts


def _write_yaml(
    path: Path,
    data: dict[str, Any],
    *,
    expected_signatures: dict[Path, tuple[int, int] | None] | None = None,
) -> None:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        for source_path, expected in (expected_signatures or {}).items():
            actual = _file_signature(source_path)
            if actual != expected:
                raise RuntimeError(f"source changed during action meta sync: {source_path}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
