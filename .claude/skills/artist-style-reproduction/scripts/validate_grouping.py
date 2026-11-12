#!/usr/bin/env python3
"""Validate artist-style grouping folders after classification.

The validator is read-only for source images. It reads image metadata directly
from PNG text and, when the project helper is available, hidden watermark data.
It never reads sidecar metadata.json files as classification evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
STYLE_DIR_RE = re.compile(r"^\d{2}_.+")
SPECIAL_ARCHIVE = "99_all_img2img_or_inpaint"
UNKNOWN_STYLE_PREFIXES = ("98_unknown_style", "unknown_style")
PARAM_KEYS = (
    "request_type",
    "model",
    "sampler",
    "steps",
    "scale",
    "cfg_rescale",
    "noise_schedule",
)


def find_project_root() -> Path:
    candidates: list[Path] = []
    env_root = os.environ.get("TAGS_MACHINE_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())

    cwd = Path.cwd()
    candidates.extend([cwd, *cwd.parents])

    script_path = Path(__file__).resolve()
    candidates.extend([script_path.parent, *script_path.parents])

    for candidate in candidates:
        if (candidate / "artist_parse" / "restore_nai_metadata_cache.py").exists():
            return candidate

    return script_path.parents[1]


PROJECT_ROOT = find_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from artist_parse.restore_nai_metadata_cache import (  # type: ignore
        extract_nai_payload,
        read_hidden_watermark,
        reference_hashes,
    )
except Exception:  # pragma: no cover - fallback for non-project use.
    extract_nai_payload = None  # type: ignore[assignment]
    read_hidden_watermark = None  # type: ignore[assignment]
    reference_hashes = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ImageContext:
    path: Path
    rel: Path
    top: str
    status: str | None
    post: str | None
    is_style_root: bool
    is_archive_root: bool
    is_unknown_root: bool


@dataclass(frozen=True)
class ImageRecord:
    ctx: ImageContext
    meta: dict[str, Any]


def iter_images(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
        and ".artist_metadata_cache" not in path.parts
    )


def context_for(root: Path, path: Path) -> ImageContext:
    rel = path.relative_to(root)
    parts = rel.parts
    top = parts[0] if parts else ""
    is_archive_root = top == SPECIAL_ARCHIVE
    is_unknown_root = top.startswith(UNKNOWN_STYLE_PREFIXES)
    is_style_root = bool(STYLE_DIR_RE.match(top)) and not is_archive_root and not top.startswith("98_")

    status: str | None = None
    post: str | None = None
    if is_style_root or is_unknown_root:
        if len(parts) >= 2:
            status = parts[1]
        if len(parts) >= 3:
            post = parts[2]
    elif is_archive_root:
        if len(parts) >= 2:
            post = parts[1]
    else:
        if len(parts) >= 2:
            post = parts[-2]

    return ImageContext(
        path=path,
        rel=rel,
        top=top,
        status=status,
        post=post,
        is_style_root=is_style_root,
        is_archive_root=is_archive_root,
        is_unknown_root=is_unknown_root,
    )


def issue(
    severity: str,
    code: str,
    message: str,
    *,
    path: Path | None = None,
    post: str | None = None,
    image: str | None = None,
    style: str | None = None,
    status: str | None = None,
    expected: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if path is not None:
        row["path"] = str(path)
    if post:
        row["post"] = post
    if image:
        row["image"] = image
    if style:
        row["style"] = style
    if status:
        row["status"] = status
    if expected:
        row["expected"] = expected
    if details:
        row["details"] = details
    return row


def read_regular_info(path: Path) -> tuple[str | None, dict[str, Any], str | None]:
    try:
        with Image.open(path) as image:
            return image.format, dict(image.info), None
    except Exception as exc:
        return None, {}, f"{type(exc).__name__}: {exc}"


def parse_comment_from_info(info: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
    if extract_nai_payload is not None:
        comment, prompt, uc = extract_nai_payload(info)
        return comment, prompt, uc

    value = info.get("Comment") or info.get("comment")
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None, "", ""
        if isinstance(parsed, dict):
            return parsed, str(parsed.get("prompt") or ""), str(parsed.get("uc") or "")
    return None, "", ""


def fallback_reference_hashes(values: Any) -> list[str]:
    import hashlib

    if not isinstance(values, list):
        return []
    return [hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16] for value in values]


def read_metadata(path: Path) -> dict[str, Any]:
    image_format, regular_info, regular_error = read_regular_info(path)
    comment, prompt, uc = parse_comment_from_info(regular_info)
    source = "regular_png_text" if comment is not None else "none"
    errors: dict[str, str] = {}
    if regular_error:
        errors["regular_png_text"] = regular_error

    if comment is None and read_hidden_watermark is not None:
        try:
            hidden_info = read_hidden_watermark(path)
            comment, prompt, uc = parse_comment_from_info(hidden_info)
            if comment is not None:
                source = "hidden_watermark"
        except Exception as exc:
            errors["hidden_watermark"] = f"{type(exc).__name__}: {exc}"

    comment = comment if isinstance(comment, dict) else {}
    ref_values = comment.get("reference_image_multiple")
    ref_count = len(ref_values) if isinstance(ref_values, list) else 0
    has_embedded_vibe = ref_count > 0
    has_vibe_params = bool(
        comment.get("reference_strength_multiple")
        or comment.get("reference_information_extracted_multiple")
        or has_embedded_vibe
    )
    hash_fn = reference_hashes or fallback_reference_hashes
    ref_hashes = hash_fn(ref_values) if isinstance(ref_values, list) else []

    return {
        "image_format": image_format,
        "metadata_source": source,
        "comment": comment,
        "prompt": prompt,
        "uc": uc,
        "errors": errors,
        "request_type": comment.get("request_type"),
        "reference_image_count": ref_count,
        "reference_image_hashes": ref_hashes,
        "has_embedded_vibe": has_embedded_vibe,
        "has_vibe_params": has_vibe_params,
        "params": {key: comment.get(key) for key in PARAM_KEYS if key in comment},
    }


def vibe_tokens(status: str | None) -> list[str]:
    if not status or not status.startswith("vibe_"):
        return []
    return [token.lower() for token in status.removeprefix("vibe_").split("_") if token]


def hash_tokens_match(expected_tokens: list[str], actual_hashes: list[str]) -> bool:
    if not expected_tokens:
        return False
    actual = [value.lower() for value in actual_hashes]
    unmatched = list(actual)
    for token in expected_tokens:
        match_index = next(
            (idx for idx, value in enumerate(unmatched) if value.startswith(token) or token.startswith(value)),
            None,
        )
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return True


def validate_directory_structure(ctx: ImageContext) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    parts = ctx.rel.parts

    if ctx.top in {"no_vibe", "missing"} or ctx.top.startswith("vibe_"):
        issues.append(
            issue(
                "hard_error",
                "DIR_STRUCTURE",
                f"{ctx.top} used as a top-level folder",
                path=ctx.path,
                post=ctx.post,
                image=ctx.path.name,
                expected="<style-family>/<status>/<post>/<image>",
            )
        )

    if ctx.is_style_root:
        if len(parts) < 4:
            issues.append(
                issue(
                    "hard_error",
                    "DIR_STRUCTURE",
                    "style folders should contain status/post/image",
                    path=ctx.path,
                    post=ctx.post,
                    image=ctx.path.name,
                    style=ctx.top,
                    status=ctx.status,
                    expected="<style-family>/<status>/<post>/<image>",
                )
            )
        elif not (
            ctx.status == "no_vibe"
            or ctx.status == "missing"
            or bool(ctx.status and ctx.status.startswith("vibe_"))
        ):
            issues.append(
                issue(
                    "warning",
                    "UNKNOWN_STATUS",
                    "second-level folder is not no_vibe, missing, or vibe_<hash>",
                    path=ctx.path,
                    post=ctx.post,
                    image=ctx.path.name,
                    style=ctx.top,
                    status=ctx.status,
                )
            )

    for idx, part in enumerate(parts):
        if part == "no_vibe" and not (ctx.is_style_root and idx == 1):
            issues.append(
                issue(
                    "hard_error",
                    "DIR_STRUCTURE",
                    "no_vibe must be second-level under a style folder",
                    path=ctx.path,
                    post=ctx.post,
                    image=ctx.path.name,
                    style=ctx.top,
                    status=ctx.status,
                )
            )
        if part == "missing" and not ((ctx.is_style_root or ctx.is_unknown_root) and idx == 1):
            issues.append(
                issue(
                    "hard_error",
                    "DIR_STRUCTURE",
                    "missing must be second-level under a style or unknown-style folder",
                    path=ctx.path,
                    post=ctx.post,
                    image=ctx.path.name,
                    style=ctx.top,
                    status=ctx.status,
                )
            )
        if part.startswith("vibe_") and not (ctx.is_style_root and idx == 1):
            issues.append(
                issue(
                    "hard_error",
                    "DIR_STRUCTURE",
                    "vibe_<hash> must be second-level under a style folder",
                    path=ctx.path,
                    post=ctx.post,
                    image=ctx.path.name,
                    style=ctx.top,
                    status=ctx.status,
                )
            )

    if ctx.is_archive_root and len(parts) < 3:
        issues.append(
            issue(
                "hard_error",
                "DIR_STRUCTURE",
                "99_all_img2img_or_inpaint should contain post/image",
                path=ctx.path,
                post=ctx.post,
                image=ctx.path.name,
                expected="99_all_img2img_or_inpaint/<post>/<image>",
            )
        )

    return issues


def validate_metadata_semantics(ctx: ImageContext, meta: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    request_type = meta.get("request_type")
    ref_count = int(meta.get("reference_image_count") or 0)
    ref_hashes = list(meta.get("reference_image_hashes") or [])

    if meta.get("metadata_source") == "none":
        issues.append(
            issue(
                "warning",
                "METADATA_MISSING",
                "no recoverable NAI metadata found in image",
                path=ctx.path,
                post=ctx.post,
                image=ctx.path.name,
                style=ctx.top,
                status=ctx.status,
                details={"errors": meta.get("errors")},
            )
        )
        return issues

    if ctx.is_style_root and ctx.status == "missing":
        if request_type == "PromptGenerateRequest" and ref_count == 0 and not meta.get("has_vibe_params"):
            issues.append(
                issue(
                    "warning",
                    "SALVAGE_CANDIDATE",
                    "normal no-vibe image found under missing",
                    path=ctx.path,
                    post=ctx.post,
                    image=ctx.path.name,
                    style=ctx.top,
                    status=ctx.status,
                    expected=f"{ctx.top}/no_vibe/{ctx.post}/{ctx.path.name}" if ctx.post else f"{ctx.top}/no_vibe/<post>/{ctx.path.name}",
                    details={"request_type": request_type, "reference_image_count": ref_count, "params": meta.get("params")},
                )
            )

    if ctx.is_archive_root:
        if ref_count > 0:
            tokens = "_".join(value[:8] for value in ref_hashes)
            issues.append(
                issue(
                    "hard_error",
                    "VIBE_PRIORITY",
                    "embedded vibe found under 99_all_img2img_or_inpaint",
                    path=ctx.path,
                    post=ctx.post,
                    image=ctx.path.name,
                    status=ctx.top,
                    expected=f"<style-family>/vibe_{tokens}/{ctx.post}" if tokens and ctx.post else "<style-family>/vibe_<hash>/<post>",
                    details={"reference_image_hashes": ref_hashes, "request_type": request_type},
                )
            )
        if request_type == "PromptGenerateRequest":
            issues.append(
                issue(
                    "hard_error",
                    "SPECIAL_ARCHIVE_HAS_NORMAL",
                    "PromptGenerateRequest found under 99_all_img2img_or_inpaint",
                    path=ctx.path,
                    post=ctx.post,
                    image=ctx.path.name,
                    status=ctx.top,
                    expected="<style-family>/no_vibe or <style-family>/vibe_<hash>",
                    details={"request_type": request_type, "reference_image_count": ref_count},
                )
            )

    return issues


def validate_group_metadata(records: list[ImageRecord]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, str], list[ImageRecord]] = defaultdict(list)

    for record in records:
        ctx = record.ctx
        if not ctx.is_style_root or not ctx.status or not ctx.post:
            continue
        if ctx.status == "no_vibe" or ctx.status.startswith("vibe_"):
            groups[(ctx.top, ctx.status, ctx.post)].append(record)

    for (style, status, post), group_records in sorted(groups.items()):
        if status == "no_vibe":
            normal_samples = [
                record
                for record in group_records
                if record.meta.get("request_type") == "PromptGenerateRequest"
                and int(record.meta.get("reference_image_count") or 0) == 0
                and not record.meta.get("has_vibe_params")
            ]
            vibe_samples = [
                record
                for record in group_records
                if int(record.meta.get("reference_image_count") or 0) > 0
                or bool(record.meta.get("has_vibe_params"))
            ]

            if not normal_samples:
                sample = group_records[0]
                issues.append(
                    issue(
                        "hard_error",
                        "NO_VIBE_GROUP_NO_NORMAL",
                        "no_vibe post has no recoverable normal no-vibe PromptGenerateRequest image",
                        path=sample.ctx.path,
                        post=post,
                        image=sample.ctx.path.name,
                        style=style,
                        status=status,
                        expected="at least one image with request_type=PromptGenerateRequest and zero vibe refs",
                        details={
                            "image_count": len(group_records),
                            "request_types": sorted({str(record.meta.get("request_type")) for record in group_records}),
                        },
                    )
                )

            if vibe_samples:
                sample = vibe_samples[0]
                issues.append(
                    issue(
                        "hard_error",
                        "NO_VIBE_GROUP_HAS_VIBE",
                        "no_vibe post contains image metadata that uses vibe",
                        path=sample.ctx.path,
                        post=post,
                        image=sample.ctx.path.name,
                        style=style,
                        status=status,
                        expected="no embedded vibe refs and no vibe params in the no_vibe post group",
                        details={
                            "vibe_image_count": len(vibe_samples),
                            "sample_reference_image_hashes": sample.meta.get("reference_image_hashes"),
                        },
                    )
                )
            continue

        if status.startswith("vibe_"):
            expected_tokens = vibe_tokens(status)
            matched_samples: list[ImageRecord] = []
            mismatched_samples: list[ImageRecord] = []
            embedded_samples: list[ImageRecord] = []
            missing_ref_samples: list[ImageRecord] = []

            for record in group_records:
                ref_count = int(record.meta.get("reference_image_count") or 0)
                ref_hashes = list(record.meta.get("reference_image_hashes") or [])
                if ref_count == 0:
                    missing_ref_samples.append(record)
                    continue
                embedded_samples.append(record)
                if hash_tokens_match(expected_tokens, ref_hashes):
                    matched_samples.append(record)
                else:
                    mismatched_samples.append(record)

            if not matched_samples:
                sample = group_records[0]
                issues.append(
                    issue(
                        "hard_error",
                        "VIBE_GROUP_METADATA_MISSING",
                        "vibe post group has no image with embedded refs matching the vibe folder",
                        path=sample.ctx.path,
                        post=post,
                        image=sample.ctx.path.name,
                        style=style,
                        status=status,
                        expected=f"at least one image with embedded refs matching {status}",
                        details={
                            "image_count": len(group_records),
                            "embedded_ref_image_count": len(embedded_samples),
                            "missing_ref_image_count": len(missing_ref_samples),
                            "observed_hashes": sorted(
                                {
                                    value
                                    for record in embedded_samples
                                    for value in list(record.meta.get("reference_image_hashes") or [])
                                }
                            ),
                        },
                    )
                )

            for record in mismatched_samples:
                issues.append(
                    issue(
                        "hard_error",
                        "VIBE_HASH_MISMATCH",
                        "embedded vibe hashes do not match the vibe folder name",
                        path=record.ctx.path,
                        post=post,
                        image=record.ctx.path.name,
                        style=style,
                        status=status,
                        expected=status,
                        details={"reference_image_hashes": record.meta.get("reference_image_hashes")},
                    )
                )

    return issues


def validate_post_consistency(contexts: list[ImageContext]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    style_roots_by_post: dict[str, set[str]] = defaultdict(set)
    statuses_by_post_style: dict[tuple[str, str], set[str]] = defaultdict(set)
    sample_paths: dict[tuple[str, str, str], Path] = {}

    for ctx in contexts:
        if not ctx.post or not ctx.is_style_root:
            continue
        style_roots_by_post[ctx.post].add(ctx.top)
        if ctx.status:
            statuses_by_post_style[(ctx.post, ctx.top)].add(ctx.status)
            sample_paths.setdefault((ctx.post, ctx.top, ctx.status), ctx.path)

    for post, roots in sorted(style_roots_by_post.items()):
        if len(roots) > 1:
            locations = sorted(roots)
            issues.append(
                issue(
                    "hard_error",
                    "POST_CROSS_STYLE",
                    "same post appears under multiple style roots",
                    post=post,
                    details={"style_roots": locations},
                )
            )

    for (post, style), statuses in sorted(statuses_by_post_style.items()):
        if "missing" in statuses and "no_vibe" in statuses:
            issues.append(
                issue(
                    "warning",
                    "POST_DUPLICATE_SALVAGE",
                    "post appears in both missing and no_vibe; count once for post-frequency",
                    post=post,
                    style=style,
                    details={
                        "statuses": sorted(statuses),
                        "missing_sample": str(sample_paths.get((post, style, "missing"), "")),
                        "no_vibe_sample": str(sample_paths.get((post, style, "no_vibe"), "")),
                    },
                )
            )

    return issues


def summarize(root: Path, images: list[Path], contexts: list[ImageContext], issues: list[dict[str, Any]]) -> dict[str, Any]:
    posts = {ctx.post for ctx in contexts if ctx.post}
    counts = defaultdict(int)
    for item in issues:
        counts[item["severity"]] += 1
        counts[item["code"]] += 1
    return {
        "root": str(root),
        "posts_scanned": len(posts),
        "images_scanned": len(images),
        "hard_errors": counts["hard_error"],
        "warnings": counts["warning"],
        "salvage_candidates": counts["SALVAGE_CANDIDATE"],
        "salvage_duplicates": counts["POST_DUPLICATE_SALVAGE"],
    }


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def format_issue(item: dict[str, Any]) -> list[str]:
    lines = [f"[{item['code']}] {item['message']}"]
    for key in ("post", "image", "style", "status", "path", "expected"):
        if item.get(key):
            lines.append(f"  {key}: {item[key]}")
    details = item.get("details")
    if isinstance(details, dict) and details:
        for key, value in details.items():
            lines.append(f"  {key}: {value}")
    return lines


def write_markdown(path: Path, summary: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    hard_errors = [item for item in issues if item["severity"] == "hard_error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    lines = [
        "# Artist Grouping Validation",
        "",
        f"Root: `{summary['root']}`",
        "Mode: read-only",
        "",
        "## Summary",
        "",
        f"- Posts scanned: {summary['posts_scanned']}",
        f"- Images scanned: {summary['images_scanned']}",
        f"- Hard errors: {summary['hard_errors']}",
        f"- Warnings: {summary['warnings']}",
        f"- Salvage candidates: {summary['salvage_candidates']}",
        f"- Salvage duplicates: {summary['salvage_duplicates']}",
        "",
        "## Hard Errors",
        "",
    ]
    if hard_errors:
        for item in hard_errors:
            lines.extend(format_issue(item))
            lines.append("")
    else:
        lines.append("- none")
        lines.append("")

    lines.extend(["## Warnings", ""])
    if warnings:
        for item in warnings:
            lines.extend(format_issue(item))
            lines.append("")
    else:
        lines.append("- none")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def validate(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    images = iter_images(root)
    contexts: list[ImageContext] = []
    records: list[ImageRecord] = []
    issues: list[dict[str, Any]] = []

    for path in images:
        ctx = context_for(root, path)
        contexts.append(ctx)
        issues.extend(validate_directory_structure(ctx))
        meta = read_metadata(path)
        records.append(ImageRecord(ctx=ctx, meta=meta))
        issues.extend(validate_metadata_semantics(ctx, meta))

    issues.extend(validate_group_metadata(records))
    issues.extend(validate_post_consistency(contexts))
    summary = summarize(root, images, contexts, issues)
    return summary, issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Grouped artist folder to validate.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for validation_report.md/json. Defaults to the grouped root.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print JSON summary only; do not write report files.",
    )
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: grouped root does not exist: {root}", file=sys.stderr)
        return 2

    summary, issues = validate(root)
    result = {"summary": summary, "issues": issues}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))

    if not args.no_write:
        output_dir = args.output_dir.expanduser().resolve() if args.output_dir else root
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "validation_report.json", result)
        write_markdown(output_dir / "validation_report.md", summary, issues)
        print(f"report_json: {output_dir / 'validation_report.json'}")
        print(f"report_md: {output_dir / 'validation_report.md'}")

    return 1 if summary["hard_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
