from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image


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
    from artist_parse.restore_nai_metadata_cache import (
        extract_nai_payload,
        read_hidden_watermark,
        reference_hashes,
        sanitize_comment,
    )
except Exception:  # pragma: no cover - supports direct script execution.
    from restore_nai_metadata_cache import (  # type: ignore
        extract_nai_payload,
        read_hidden_watermark,
        reference_hashes,
        sanitize_comment,
    )


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
SUMMARY_PARAM_KEYS = (
    "request_type",
    "sampler",
    "steps",
    "scale",
    "cfg_rescale",
    "uncond_scale",
    "dynamic_thresholding",
    "noise_schedule",
    "sm",
    "sm_dyn",
    "skip_cfg_above_sigma",
    "skip_cfg_below_sigma",
    "legacy_v3_extend",
    "add_original_image",
    "seed",
    "width",
    "height",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a flat original/generated image comparison package."
    )
    parser.add_argument("images", nargs="+", help="Exactly two image paths from SendTo.")
    parser.add_argument("--output-dir", help="Optional compare output directory.")
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the output folder after creating it.",
    )
    args = parser.parse_args()

    image_paths = [Path(value).expanduser() for value in args.images]
    image_paths = [path.resolve() for path in image_paths if path.suffix.lower() in IMAGE_EXTENSIONS]
    if len(image_paths) != 2:
        print("ERROR: select exactly two image files.")
        print("Received:")
        for value in args.images:
            print(f"  {value}")
        return 2
    for path in image_paths:
        if not path.is_file():
            print(f"ERROR: image does not exist: {path}")
            return 2

    source_path, generated_path, role_note = infer_roles(image_paths[0], image_paths[1])
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else default_output_dir(source_path, generated_path)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    create_compare_package(source_path, generated_path, output_dir, role_note=role_note)
    print(f"compare_dir: {output_dir}")
    if not args.no_open:
        try:
            os.startfile(str(output_dir))  # type: ignore[attr-defined]
        except Exception:
            pass
    return 0


def infer_roles(first: Path, second: Path) -> tuple[Path, Path, str]:
    first_source = source_score(first)
    second_source = source_score(second)
    first_generated = generated_score(first)
    second_generated = generated_score(second)

    if first_source + second_generated > second_source + first_generated:
        return first, second, "inferred: first=source, second=generated"
    if second_source + first_generated > first_source + second_generated:
        return second, first, "inferred: second=source, first=generated"
    return first, second, "ambiguous: using selection order as source/generated"


def source_score(path: Path) -> int:
    text = normalized_path_text(path)
    stem = path.stem.lower()
    score = 0
    if "\\groups\\" in text or "\\origin\\" in text:
        score += 5
    if stem.startswith("source_"):
        score += 4
    if re.match(r"^\d+_p\d+$", stem):
        score += 2
    return score


def generated_score(path: Path) -> int:
    text = normalized_path_text(path)
    stem = path.stem.lower()
    score = 0
    if "\\repro_tests\\" in text or "\\reproduction\\" in text:
        score += 5
    if "blackboard_next_character" in text or "run_raw" in text:
        score += 4
    if stem.startswith("generated") or "generated" in stem:
        score += 4
    return score


def normalized_path_text(path: Path) -> str:
    return str(path).replace("/", "\\").lower()


def default_output_dir(source_path: Path, generated_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_name = short_name(source_path.stem)
    generated_name = short_name(generated_path.stem)
    return generated_path.parent / f"manual_compare_{source_name}_vs_{generated_name}_{stamp}"


def find_named_ancestor(path: Path, name: str) -> Path | None:
    for parent in [path, *path.parents]:
        if parent.name.lower() == name.lower():
            return parent
    return None


def short_name(value: str, limit: int = 34) -> str:
    safe = re.sub(r'[<>:"/\\|?*\s]+', "_", value).strip("._")
    if len(safe) <= limit:
        return safe or "image"
    digest = hashlib.sha1(safe.encode("utf-8")).hexdigest()[:8]
    return f"{safe[: limit - 9]}_{digest}"


def create_compare_package(
    source_path: Path,
    generated_path: Path,
    output_dir: Path,
    *,
    role_note: str,
) -> None:
    source_meta = read_best_metadata(source_path)
    generated_meta = read_best_metadata(generated_path)

    source_copy = output_dir / f"source_{source_path.stem}{source_path.suffix.lower()}"
    generated_copy = output_dir / f"generated_current_tags{generated_path.suffix.lower()}"
    shutil.copy2(source_path, source_copy)
    shutil.copy2(generated_path, generated_copy)

    write_text(output_dir / "source_prompt.txt", source_meta["prompt"])
    write_text(output_dir / "generated_prompt.txt", generated_meta["prompt"])
    write_text(output_dir / "source_uc.txt", source_meta["uc"])
    write_text(output_dir / "generated_uc.txt", generated_meta["uc"])

    write_json(output_dir / "source_comment.json", source_meta["comment"])
    write_json(output_dir / "generated_comment.json", generated_meta["comment"])
    write_json(output_dir / "source_png_text.json", source_meta["png_text"])
    write_json(output_dir / "generated_png_text.json", generated_meta["png_text"])

    source_slim = build_slim(source_meta, source_copy)
    generated_slim = build_slim(generated_meta, generated_copy)
    write_json(output_dir / "source_slim.json", source_slim)
    write_json(output_dir / "generated_slim.json", generated_slim)
    write_json(
        output_dir / "metadata_sources.json",
        {
            "source": source_meta["metadata_source"],
            "generated": generated_meta["metadata_source"],
            "role_note": role_note,
            "source_errors": source_meta["errors"],
            "generated_errors": generated_meta["errors"],
        },
    )

    write_prompt_diff(
        output_dir / "prompt_unified.diff",
        source_meta["prompt"],
        generated_meta["prompt"],
    )
    write_optional_node_files(output_dir, generated_meta)
    write_summary(
        output_dir / "diff_summary.txt",
        source_path,
        generated_path,
        source_meta,
        generated_meta,
        role_note,
    )


def read_best_metadata(path: Path) -> dict[str, Any]:
    errors: dict[str, str] = {}
    image_format, regular_info = read_regular_info(path, errors)
    png_text = decode_info_values(regular_info)

    comment, prompt, uc = extract_nai_payload(regular_info)
    if comment is not None:
        return metadata_record(
            path,
            image_format,
            png_text,
            comment,
            prompt,
            uc,
            "regular_png_text",
            errors,
        )

    try:
        hidden_info = read_hidden_watermark(path)
        comment, prompt, uc = extract_nai_payload(hidden_info)
        if comment is not None:
            return metadata_record(
                path,
                image_format,
                png_text,
                comment,
                prompt,
                uc,
                "hidden_watermark",
                errors,
            )
    except Exception as exc:
        errors["hidden_watermark"] = repr(exc)

    return {
        "path": str(path),
        "image_format": image_format,
        "png_text": png_text,
        "metadata_source": "none",
        "prompt": "",
        "uc": "",
        "comment": {},
        "raw_comment": {},
        "errors": errors,
    }


def read_regular_info(path: Path, errors: dict[str, str]) -> tuple[str | None, dict[str, Any]]:
    try:
        with Image.open(path) as image:
            return image.format, dict(image.info)
    except Exception as exc:
        errors["regular_png_text"] = repr(exc)
        return None, {}


def decode_info_values(info: dict[str, Any]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in info.items():
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError:
                value = value.decode("latin-1", errors="replace")
        if isinstance(value, str):
            text = value.strip()
            if text[:1] in {"{", "["}:
                try:
                    decoded[key] = json.loads(text)
                    continue
                except json.JSONDecodeError:
                    pass
        decoded[key] = to_jsonable(value)
    return decoded

def normalized_abs(path: Path) -> str:
    try:
        return str(path.resolve()).replace("/", "\\").lower()
    except Exception:
        return str(path).replace("/", "\\").lower()

def metadata_record(
    path: Path,
    image_format: str | None,
    png_text: dict[str, Any],
    comment: dict[str, Any],
    prompt: str,
    uc: str,
    metadata_source: str,
    errors: dict[str, str],
) -> dict[str, Any]:
    raw_comment = dict(comment)
    clean_comment = sanitize_comment(raw_comment, reference_mode="hashes")
    clean_comment = to_jsonable(clean_comment)
    return {
        "path": str(path),
        "image_format": image_format,
        "png_text": png_text,
        "metadata_source": metadata_source,
        "prompt": str(prompt or ""),
        "uc": str(uc or ""),
        "comment": clean_comment,
        "raw_comment": raw_comment,
        "errors": errors,
    }


def build_slim(meta: dict[str, Any], image_path: Path) -> dict[str, Any]:
    comment = meta.get("comment") if isinstance(meta.get("comment"), dict) else {}
    raw_comment = meta.get("raw_comment") if isinstance(meta.get("raw_comment"), dict) else {}
    ref_values = raw_comment.get("reference_image_multiple")
    return {
        "image_path": str(image_path),
        "metadata_source": meta.get("metadata_source"),
        "prompt": meta.get("prompt", ""),
        "uc": meta.get("uc", ""),
        "params": {key: comment.get(key) for key in SUMMARY_PARAM_KEYS if key in comment},
        "reference_information_extracted_multiple": comment.get("reference_information_extracted_multiple"),
        "reference_strength_multiple": comment.get("reference_strength_multiple"),
        "reference_image_count": len(ref_values) if isinstance(ref_values, list) else comment.get("reference_image_count", 0),
        "reference_image_hashes": reference_hashes(ref_values) if isinstance(ref_values, list) else comment.get("reference_image_hashes", []),
    }


def write_prompt_diff(path: Path, source_prompt: str, generated_prompt: str) -> None:
    diff = difflib.unified_diff(
        source_prompt.split(","),
        generated_prompt.split(","),
        fromfile="source_prompt.txt",
        tofile="generated_prompt.txt",
        lineterm="",
    )
    write_text(path, "\n".join(diff) + "\n")


def write_optional_node_files(output_dir: Path, generated_meta: dict[str, Any]) -> None:
    png_text = generated_meta.get("png_text") if isinstance(generated_meta.get("png_text"), dict) else {}
    node_keys = ("character", "artist", "action", "background", "topic")
    nodes = {key: png_text.get(key) for key in node_keys if key in png_text}
    if nodes:
        write_json(output_dir / "generated_nodes.json", nodes)
    action = nodes.get("action")
    if is_meaningful_node_value(action):
        write_text(output_dir / "action_used.txt", action.strip())
    artist = nodes.get("artist")
    if is_meaningful_node_value(artist):
        artist_tags = resolve_artist_tags(str(artist))
        write_text(output_dir / "tags_used.txt", artist_tags if artist_tags is not None else str(artist))


def is_meaningful_node_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text and text.lower() not in {"none", "null", "[]", "{}"})


def resolve_artist_tags(value: str) -> str | None:
    artist_path = Path(value)
    candidates: list[Path] = []
    if artist_path.is_absolute():
        candidates.append(artist_path / "tags.txt" if artist_path.is_dir() else artist_path)
    else:
        design_root = PROJECT_ROOT / "design"
        candidates.extend(design_root.glob(f"*/{value}/tags.txt"))
        candidates.extend(design_root.glob(f"画风/{value}/tags.txt"))

    for candidate in candidates:
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8")
            except Exception:
                return None
    return None


def write_summary(
    path: Path,
    source_path: Path,
    generated_path: Path,
    source_meta: dict[str, Any],
    generated_meta: dict[str, Any],
    role_note: str,
) -> None:
    source_comment = source_meta.get("comment") if isinstance(source_meta.get("comment"), dict) else {}
    generated_comment = generated_meta.get("comment") if isinstance(generated_meta.get("comment"), dict) else {}
    param_diff = compare_params(source_comment, generated_comment, exclude=())
    param_diff_no_resolution = compare_params(source_comment, generated_comment, exclude=("width", "height"))

    source_tokens = split_prompt_tokens(source_meta.get("prompt", ""))
    generated_tokens = split_prompt_tokens(generated_meta.get("prompt", ""))
    generated_set = set(generated_tokens)
    source_set = set(source_tokens)

    lines = [
        f"out_dir: {path.parent}",
        f"source: {source_path}",
        f"generated: {generated_path}",
        f"role_note: {role_note}",
        f"source_metadata: {source_meta.get('metadata_source')}",
        f"generated_metadata: {generated_meta.get('metadata_source')}",
        "",
        "PARAM_DIFF",
        *(param_diff or ["- none"]),
        "",
        "PARAM_DIFF_NO_RESOLUTION",
        *(param_diff_no_resolution or ["- none"]),
        "",
        f"source_prompt_token_count: {len(source_tokens)}",
        f"generated_prompt_token_count: {len(generated_tokens)}",
        f"common_prompt_tokens: {sorted(source_set & generated_set)}",
        f"source_only_tokens: {[token for token in source_tokens if token not in generated_set]}",
        f"generated_only_tokens: {[token for token in generated_tokens if token not in source_set]}",
    ]
    write_text(path, "\n".join(lines) + "\n")


def compare_params(
    source_comment: dict[str, Any],
    generated_comment: dict[str, Any],
    *,
    exclude: tuple[str, ...],
) -> list[str]:
    lines: list[str] = []
    keys = [key for key in SUMMARY_PARAM_KEYS if key not in exclude]
    for key in keys:
        source_value = source_comment.get(key, "<missing>")
        generated_value = generated_comment.get(key, "<missing>")
        if source_value != generated_value:
            lines.append(f"- {key}: source={source_value!r} generated={generated_value!r}")
    return lines


def split_prompt_tokens(prompt: Any) -> list[str]:
    return [token.strip() for token in str(prompt or "").split(",") if token.strip()]


def write_text(path: Path, text: str) -> None:
    path.write_text(text or "", encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(to_jsonable(data), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1", errors="replace")
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return repr(value)


if __name__ == "__main__":
    raise SystemExit(main())
