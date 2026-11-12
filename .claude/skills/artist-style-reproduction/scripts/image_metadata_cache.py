#!/usr/bin/env python3
"""Build a direct-image metadata cache for artist-style analysis.

The cache is intentionally derived only from image files. It must not import
sidecar metadata or previous classifier outputs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image


SCHEMA_VERSION = 1
DEFAULT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def norm_path(path: Path) -> str:
    return str(path.resolve())


def stat_key(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {
        "path": norm_path(path),
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
    }


def load_cache(cache_path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not cache_path.exists():
        return rows
    with cache_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("schema_version") != SCHEMA_VERSION:
                continue
            path = row.get("path")
            if isinstance(path, str):
                rows[path] = row
    return rows


def is_fresh(row: dict[str, Any], key: dict[str, Any]) -> bool:
    return (
        row.get("path") == key["path"]
        and row.get("size") == key["size"]
        and row.get("mtime_ns") == key["mtime_ns"]
    )


def safe_info(info: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in info.items():
        if isinstance(value, bytes):
            result[key] = value.decode("utf-8", errors="replace")
        else:
            result[key] = str(value)
    return result


def parse_comment(comment: str) -> tuple[Any, str | None]:
    if not comment:
        return None, None
    try:
        return json.loads(comment), None
    except Exception as exc:  # keep broad; metadata can be arbitrary text
        return None, f"{type(exc).__name__}: {exc}"


def read_image_metadata(path: Path) -> dict[str, Any]:
    key = stat_key(path)
    row: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        **key,
        "name": path.name,
        "post": path.parent.name,
        "suffix": path.suffix.lower(),
        "ok": False,
        "source": "direct_image_read",
    }
    try:
        with Image.open(path) as image:
            info = safe_info(dict(image.info))
            row["format"] = image.format
            row["mode"] = image.mode
            row["width"] = image.width
            row["height"] = image.height
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row

    comment = info.get("Comment") or info.get("comment") or ""
    parsed, parse_error = parse_comment(comment)

    row.update(
        {
            "ok": True,
            "png_info": info,
            "comment": comment,
            "comment_json": parsed,
            "comment_parse_error": parse_error,
        }
    )

    if isinstance(parsed, dict):
        for key_name in (
            "prompt",
            "uc",
            "negative_prompt",
            "model",
            "sampler",
            "steps",
            "scale",
            "request_type",
            "seed",
        ):
            if key_name in parsed:
                row[key_name] = parsed.get(key_name)
    return row


def iter_images(root: Path, extensions: set[str]) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in extensions
    )


def write_cache(cache_path: Path, rows: list[dict[str, Any]]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp_path.replace(cache_path)


def build_cache(root: Path, cache_path: Path, refresh: bool, extensions: set[str]) -> dict[str, Any]:
    old_rows = load_cache(cache_path)
    output_rows: list[dict[str, Any]] = []
    counts = {
        "images": 0,
        "hits": 0,
        "misses": 0,
        "stale": 0,
        "errors": 0,
    }

    for path in iter_images(root, extensions):
        counts["images"] += 1
        key = stat_key(path)
        cached = old_rows.get(key["path"])
        if cached and not refresh and is_fresh(cached, key):
            counts["hits"] += 1
            output_rows.append(cached)
            continue
        if cached:
            counts["stale"] += 1
        else:
            counts["misses"] += 1
        row = read_image_metadata(path)
        if not row.get("ok"):
            counts["errors"] += 1
        output_rows.append(row)

    write_cache(cache_path, output_rows)
    return {
        "root": norm_path(root),
        "cache_path": norm_path(cache_path),
        **counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Artist corpus or grouped folder to scan.")
    parser.add_argument(
        "--cache",
        type=Path,
        help="Cache JSONL path. Defaults to <root>/.artist_metadata_cache/image_metadata.jsonl.",
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore existing cache rows.")
    parser.add_argument(
        "--ext",
        action="append",
        default=[],
        help="Image extension to include, e.g. --ext .png. May be repeated.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    cache_path = (
        args.cache.resolve()
        if args.cache
        else root / ".artist_metadata_cache" / "image_metadata.jsonl"
    )
    extensions = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in args.ext}
    if not extensions:
        extensions = DEFAULT_EXTENSIONS

    summary = build_cache(root, cache_path, args.refresh, extensions)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
