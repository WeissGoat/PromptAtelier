from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tags_machine_core.verification.image_params import (
    read_image_parameters,
    read_png_dimensions,
)
from tags_machine_core.verification.render_params import (
    compare_render_parameters,
    normalize_render_parameters,
)


IMAGE_COMPARISON_REPORT_SCHEMA = "tags-machine-core.image-comparison-report/v1"
GENERATION_RESULT_SCHEMA = "tags-machine-core.generation-result/v1"
VISUAL_RESULTS = ("pending", "pass", "fail", "review")


def build_image_comparison_report(
    legacy_image: str | Path,
    core_generation_result: str | Path,
    *,
    core_image: str | Path | None = None,
    visual_result: str = "pending",
    visual_notes: list[str] | None = None,
) -> dict[str, Any]:
    """生成旧图与 core 出图的单 case 对比报告。"""

    visual_result = _normalize_visual_result(visual_result)
    legacy_path = Path(legacy_image)
    generation_result_path = Path(core_generation_result)
    generation_result = _load_generation_result(generation_result_path)
    core_path = (
        Path(core_image)
        if core_image is not None
        else _first_generation_result_image(generation_result, base_dir=generation_result_path.parent)
    )

    legacy_summary, legacy_params = _image_summary(legacy_path)
    core_summary, core_params = _image_summary(core_path) if core_path else _missing_core_image()
    parameter_diff = _parameter_diff_summary(
        legacy_params,
        core_params,
        missing_message="Unable to compare legacy/core PNG parameters",
    )
    core_request_vs_png = _parameter_diff_summary(
        generation_result,
        core_params,
        missing_message="Unable to compare GenerationResult PNG info/core PNG parameters",
    )

    parameter_match = bool(parameter_diff["match"] and core_request_vs_png["match"])
    visual = _visual_check(visual_result, visual_notes or [])
    return {
        "schema": IMAGE_COMPARISON_REPORT_SCHEMA,
        "result": "pass" if parameter_match else "fail",
        "match": parameter_match,
        "acceptance_ready": parameter_match and visual_result == "pass",
        "generation_result": _generation_result_summary(
            generation_result,
            generation_result_path,
            selected_core_image=core_path,
        ),
        "legacy_image": legacy_summary,
        "core_image": core_summary,
        "parameter_diff": parameter_diff,
        "core_request_vs_png": core_request_vs_png,
        "visual": visual,
        "visual_check": visual,
    }


def _load_generation_result(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected GenerationResult JSON object: {path}")
    return data


def _first_generation_result_image(data: dict[str, Any], *, base_dir: Path) -> Path | None:
    images = data.get("images")
    if not isinstance(images, list) or not images:
        return None
    first = images[0]
    if not isinstance(first, dict):
        return None
    raw_path = first.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    path = Path(raw_path)
    return path if path.is_absolute() else base_dir / path


def _image_summary(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "png_parameters_readable": False,
    }
    if not path.exists():
        summary["error"] = "Image file does not exist"
        return summary, None
    if not path.is_file():
        summary["error"] = "Image path is not a file"
        return summary, None

    summary["bytes"] = path.stat().st_size
    summary["sha256"] = _file_sha256(path)
    try:
        summary["dimensions"] = read_png_dimensions(path)
    except Exception as exc:
        summary["dimension_error"] = str(exc)

    try:
        params = read_image_parameters(path)
    except Exception as exc:
        summary["png_error"] = str(exc)
        return summary, None

    summary["png_parameters_readable"] = True
    png_text = params.get("png_text")
    summary["png_text_keys"] = sorted(png_text) if isinstance(png_text, dict) else []
    summary["normalized"] = normalize_render_parameters(params)
    return summary, params


def _missing_core_image() -> tuple[dict[str, Any], None]:
    return (
        {
            "path": None,
            "exists": False,
            "png_parameters_readable": False,
            "error": "GenerationResult has no image path and --core-image was not provided",
        },
        None,
    )


def _parameter_diff_summary(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    *,
    missing_message: str,
) -> dict[str, Any]:
    if left is None or right is None:
        return {
            "match": False,
            "normalized_equal": False,
            "diff_count": None,
            "diffs": [],
            "error": missing_message,
        }

    diffs = [diff.as_dict() for diff in compare_render_parameters(left, right)]
    return {
        "match": not diffs,
        "normalized_equal": not diffs,
        "diff_count": len(diffs),
        "diffs": diffs,
        "left_normalized": normalize_render_parameters(left),
        "right_normalized": normalize_render_parameters(right),
    }


def _generation_result_summary(
    data: dict[str, Any],
    path: Path,
    *,
    selected_core_image: Path | None,
) -> dict[str, Any]:
    images = data.get("images")
    return {
        "path": str(path),
        "exists": path.exists(),
        "schema": data.get("schema"),
        "schema_valid": data.get("schema") == GENERATION_RESULT_SCHEMA,
        "backend": data.get("backend"),
        "image_count": len(images) if isinstance(images, list) else 0,
        "selected_core_image": str(selected_core_image) if selected_core_image else None,
    }


def _visual_check(result: str, notes: list[str]) -> dict[str, Any]:
    # 视觉项由人工填写；pending 不影响参数门禁，只表示还没完成肉眼验收。
    field_result = result if result in {"pass", "fail", "review"} else "pending"
    return {
        "result": result,
        "subject": field_result,
        "action": field_result,
        "camera": field_result,
        "style": field_result,
        "notes": notes,
    }


def _normalize_visual_result(value: str) -> str:
    result = str(value or "pending").strip().lower()
    if result not in VISUAL_RESULTS:
        expected = ", ".join(VISUAL_RESULTS)
        raise ValueError(f"Unsupported visual result: {value!r}; expected one of {expected}")
    return result


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
