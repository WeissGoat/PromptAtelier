from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.contracts import utc_now_iso
from tags_machine_core.verification.image_params import read_image_parameters
from tags_machine_core.verification.render_params import (
    compare_render_parameters,
    load_render_parameter_source,
    normalize_render_parameters,
)


ACCEPTANCE_SCHEMA = "tags-machine-core.acceptance-record/v1"
ACCEPTANCE_ARCHIVE_SCHEMA = "tags-machine-core.acceptance-archive/v1"
ACCEPTANCE_SUITE_MANIFEST_SCHEMA = "tags-machine-core.acceptance-suite/v1"
ACCEPTANCE_SUITE_SCHEMA = "tags-machine-core.acceptance-suite-verification/v1"
ACCEPTANCE_ORACLE_KINDS = ("legacy_oracle", "fixture")
DEFAULT_ACCEPTANCE_ORACLE_KIND = "legacy_oracle"
MINIMUM_ACCEPTANCE_CASES = (
    "default_action",
    "foot_detail",
    "hand_detail",
    "complex_character",
    "reference_style",
)
MINIMUM_SCOPE_CASES = {
    "foot_detail": {
        "character_scope": "foot_detail",
        "included_any": ("feet",),
        "suppressed_all": ("hair", "eyes", "upper_clothes"),
    },
    "hand_detail": {
        "character_scope": "hand_detail",
        "included_any": ("hands", "hand"),
        "suppressed_all": ("hair", "eyes", "upper_clothes", "feet"),
    },
}
MINIMUM_DEFAULT_ACTION_REQUIRED_PARAMS = (
    "prompt",
    "negative_prompt",
    "seed",
    "width",
    "height",
    "sampler",
    "steps",
    "scale",
    "cfg_rescale",
    "noise_schedule",
    "v4_prompt",
    "v4_negative_prompt",
    "reference_image_multiple",
    "reference_strength_multiple",
    "reference_information_extracted_multiple",
    "director_reference_images",
)
MINIMUM_DEFAULT_ACTION_EMPTY_ARRAY_PARAMS = (
    "reference_image_multiple",
    "reference_strength_multiple",
    "reference_information_extracted_multiple",
    "director_reference_images",
)
MINIMUM_COMPLEX_CHARACTER_REQUIRED_INCLUDED = ("hair", "eyes", "upper_clothes")
MINIMUM_SUPPRESSED_SECTION_PROMPT_TERMS = {
    "hair": ("hair",),
    "eyes": ("eyes",),
    "upper_clothes": (
        "school uniform",
        "shirt",
        "jacket",
        "upper clothes",
        "upper_clothes",
    ),
    "feet": ("feet", "foot", "bare soles", "soles", "toes"),
}
ACCEPTANCE_RECORD_EXTENSIONS = {".json", ".yaml", ".yml"}
ACCEPTANCE_PATH_FIELDS = {
    "source_path",
    "params_path",
    "image_path",
    "render_request_path",
    "prompt_bundle_path",
    "generation_result_path",
    "legacy_source",
    "core_source",
    "legacy_image",
    "core_image",
    "prompt_bundle",
    "generation_result",
    "case_dir",
    "resolved_path",
}


def build_acceptance_record(
    *,
    case_id: str,
    legacy_source: str | Path,
    core_source: str | Path,
    legacy_image: str | Path | None = None,
    core_image: str | Path | None = None,
    prompt_bundle: str | Path | None = None,
    generation_result: str | Path | None = None,
    whitelist: list[dict[str, str]] | None = None,
    intentional_differences: list[dict[str, str]] | None = None,
    notes: list[str] | None = None,
    oracle_kind: str = DEFAULT_ACCEPTANCE_ORACLE_KIND,
) -> dict[str, Any]:
    legacy_source_path = Path(legacy_source)
    core_source_path = Path(core_source)
    oracle_kind = _normalize_oracle_kind(oracle_kind)
    legacy_image_path = _effective_image_path(legacy_source_path, legacy_image)
    core_image_path = _effective_image_path(core_source_path, core_image)
    generation_result_path = Path(generation_result) if generation_result else None
    legacy_data = load_render_parameter_source(legacy_source_path)
    core_data = load_render_parameter_source(core_source_path)
    diffs = [diff.as_dict() for diff in compare_render_parameters(legacy_data, core_data)]
    whitelist = _normalize_path_reason_entries(whitelist)
    intentional_differences = _normalize_path_reason_entries(intentional_differences)
    whitelisted_paths = {entry["path"] for entry in whitelist}
    intentional_paths = {entry["path"] for entry in intentional_differences}
    approved_paths = whitelisted_paths | intentional_paths
    unapproved_diffs = [diff for diff in diffs if diff["path"] not in approved_paths]
    whitelisted_diff_count = sum(1 for diff in diffs if diff["path"] in whitelisted_paths)
    intentional_diff_count = sum(1 for diff in diffs if diff["path"] in intentional_paths)

    record = {
        "schema": ACCEPTANCE_SCHEMA,
        "case_id": case_id,
        "created_at": utc_now_iso(),
        "oracle_kind": oracle_kind,
        "legacy": _legacy_record_paths(
            source=legacy_source_path,
            image=legacy_image_path,
        ),
        "core": _core_record_paths(
            source=core_source_path,
            image=core_image_path,
            prompt_bundle=Path(prompt_bundle) if prompt_bundle else None,
            generation_result=generation_result_path,
        ),
        "diff": {
            "normalized_equal": not diffs,
            "diff_count": len(diffs),
            "approved_diff_count": len(diffs) - len(unapproved_diffs),
            "whitelisted_diff_count": whitelisted_diff_count,
            "intentional_diff_count": intentional_diff_count,
            "unapproved_diff_count": len(unapproved_diffs),
            "diffs": diffs,
            "unapproved_diffs": unapproved_diffs,
            "whitelist": whitelist,
            "intentional_differences": intentional_differences,
        },
        "intentional_differences": intentional_differences,
        "composition": _load_composition(
            core_data=core_data,
            prompt_bundle=Path(prompt_bundle) if prompt_bundle else None,
        ),
        "normalized": {
            "legacy": normalize_render_parameters(legacy_data),
            "core": normalize_render_parameters(core_data),
        },
        "image_evidence": {
            "legacy": _image_evidence(legacy_image_path),
            "core": _image_evidence(core_image_path),
        },
        "generation_result_evidence": _generation_result_evidence(
            generation_result_path,
            core_data=core_data,
        ),
        "prompt_bundle_contract_evidence": _prompt_bundle_contract_evidence(
            Path(prompt_bundle) if prompt_bundle else None,
        ),
        "notes": notes or [],
    }
    record["result"] = (
        "pass"
        if (
            not unapproved_diffs
            and _generation_result_evidence_pass(record)
            and _prompt_bundle_contract_evidence_pass(record)
        )
        else "fail"
    )
    return record


def archive_acceptance_case(
    *,
    case_id: str,
    output_dir: str | Path,
    legacy_source: str | Path,
    core_source: str | Path,
    legacy_image: str | Path | None = None,
    core_image: str | Path | None = None,
    prompt_bundle: str | Path | None = None,
    generation_result: str | Path | None = None,
    whitelist: list[dict[str, str]] | None = None,
    intentional_differences: list[dict[str, str]] | None = None,
    notes: list[str] | None = None,
    manifest: str | Path | None = None,
    required_cases: list[str] | None = None,
    update_manifest: bool = True,
    overwrite: bool = False,
    record_format: str = "yaml",
    oracle_kind: str = DEFAULT_ACCEPTANCE_ORACLE_KIND,
) -> dict[str, Any]:
    """归档一条旧项目 oracle 对照样例，生成可回放的 record 和 suite manifest。"""

    case_id = _validate_case_id(case_id)
    output_dir = Path(output_dir)
    case_dir = output_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    legacy_dir = case_dir / "legacy"
    core_dir = case_dir / "core"
    legacy_source_copy = _copy_acceptance_artifact(
        legacy_source,
        legacy_dir,
        _artifact_filename("source", legacy_source),
        overwrite=overwrite,
    )
    core_source_copy = _copy_acceptance_artifact(
        core_source,
        core_dir,
        _artifact_filename("render_request", core_source),
        overwrite=overwrite,
    )
    legacy_image_copy = _copy_optional_acceptance_artifact(
        legacy_image,
        legacy_dir,
        _artifact_filename("image", legacy_image) if legacy_image else None,
        overwrite=overwrite,
        fallback=legacy_source_copy if _is_png_path(legacy_source_copy) else None,
    )
    core_image_copy = _copy_optional_acceptance_artifact(
        core_image,
        core_dir,
        _artifact_filename("image", core_image) if core_image else None,
        overwrite=overwrite,
        fallback=core_source_copy if _is_png_path(core_source_copy) else None,
    )
    prompt_bundle_copy = _copy_optional_acceptance_artifact(
        prompt_bundle,
        core_dir,
        _artifact_filename("prompt_bundle", prompt_bundle) if prompt_bundle else None,
        overwrite=overwrite,
    )
    generation_result_copy = _copy_optional_acceptance_artifact(
        generation_result,
        core_dir,
        _artifact_filename("generation_result", generation_result) if generation_result else None,
        overwrite=overwrite,
    )
    _rewrite_generation_result_image_paths(
        generation_result_copy,
        source_generation_result=Path(generation_result) if generation_result else None,
        source_core_image=_generation_result_source_core_image(core_image, core_source),
        archived_core_image=core_image_copy,
    )

    record = build_acceptance_record(
        case_id=case_id,
        legacy_source=legacy_source_copy,
        core_source=core_source_copy,
        legacy_image=legacy_image_copy,
        core_image=core_image_copy,
        prompt_bundle=prompt_bundle_copy,
        generation_result=generation_result_copy,
        whitelist=whitelist,
        intentional_differences=intentional_differences,
        notes=notes,
        oracle_kind=oracle_kind,
    )
    record["archive"] = {
        "schema": ACCEPTANCE_ARCHIVE_SCHEMA,
        "case_dir": str(case_dir),
        "artifacts": _archive_artifacts(
            legacy_source=legacy_source_copy,
            core_source=core_source_copy,
            legacy_image=legacy_image_copy,
            core_image=core_image_copy,
            prompt_bundle=prompt_bundle_copy,
            generation_result=generation_result_copy,
        ),
    }
    record = _relativize_acceptance_record_paths(record, case_dir)

    record_path = case_dir / f"acceptance.{_record_suffix(record_format)}"
    _write_acceptance_document(record, record_path, output_format=record_format)

    manifest_path: Path | None = None
    if update_manifest:
        manifest_path = Path(manifest) if manifest else output_dir / "suite.yaml"
        _upsert_acceptance_suite_manifest(
            manifest_path,
            record_path=record_path,
            required_cases=required_cases or [],
        )

    return {
        "schema": ACCEPTANCE_ARCHIVE_SCHEMA,
        "case_id": case_id,
        "case_dir": str(case_dir),
        "record_path": str(record_path),
        "manifest_path": str(manifest_path) if manifest_path is not None else None,
        "result": record["result"],
        "record": record,
    }


def load_acceptance_record(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Expected acceptance record mapping: {path}")
    return data


def verify_acceptance_record(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    record = load_acceptance_record(path)
    if record.get("schema") != ACCEPTANCE_SCHEMA:
        raise ValueError(f"Unsupported acceptance record schema: {record.get('schema')}")

    base_dir = path.parent
    rebuilt = build_acceptance_record(
        case_id=str(record.get("case_id") or path.stem),
        legacy_source=_resolve_record_path(_record_source(record, "legacy"), base_dir),
        core_source=_resolve_record_path(_record_source(record, "core"), base_dir),
        legacy_image=_optional_record_path((record.get("legacy") or {}).get("image_path"), base_dir),
        core_image=_optional_record_path((record.get("core") or {}).get("image_path"), base_dir),
        prompt_bundle=_optional_record_path(
            (record.get("core") or {}).get("prompt_bundle_path"),
            base_dir,
        ),
        generation_result=_optional_record_path(
            (record.get("core") or {}).get("generation_result_path"),
            base_dir,
        ),
        whitelist=(record.get("diff") or {}).get("whitelist") or [],
        intentional_differences=_record_intentional_differences(record),
        notes=record.get("notes") or [],
        oracle_kind=_record_oracle_kind(record),
    )
    return {
        "schema": "tags-machine-core.acceptance-verification/v1",
        "record_path": str(path),
        "case_id": rebuilt["case_id"],
        "oracle_kind": rebuilt["oracle_kind"],
        "match": rebuilt["result"] == "pass",
        "result": rebuilt["result"],
        "diff": rebuilt["diff"],
        "intentional_differences": rebuilt["intentional_differences"],
        "composition": rebuilt["composition"],
        "normalized": rebuilt["normalized"],
        "image_evidence": rebuilt["image_evidence"],
        "generation_result_evidence": rebuilt["generation_result_evidence"],
        "prompt_bundle_contract_evidence": rebuilt["prompt_bundle_contract_evidence"],
    }


def verify_acceptance_suite(
    path: str | Path,
    *,
    required_cases: list[str] | None = None,
    require_minimum_set: bool = False,
    require_legacy_oracle: bool = False,
    require_legacy_evidence: bool = False,
) -> dict[str, Any]:
    path = Path(path)
    record_paths, manifest_required_cases = _suite_record_paths(path)
    required = _unique_strings(
        [
            *(manifest_required_cases or []),
            *(required_cases or []),
            *(MINIMUM_ACCEPTANCE_CASES if require_minimum_set else ()),
        ]
    )

    results: list[dict[str, Any]] = []
    for record_path in record_paths:
        try:
            results.append(verify_acceptance_record(record_path))
        except Exception as exc:  # 批量回放时保留单条错误，不中断整个 suite。
            results.append(
                {
                    "schema": "tags-machine-core.acceptance-verification/v1",
                    "record_path": str(record_path),
                    "case_id": record_path.stem,
                    "oracle_kind": "unknown",
                    "match": False,
                    "result": "error",
                    "error": str(exc),
                    "diff": {},
                    "composition": {},
                }
            )

    case_ids = [str(item.get("case_id")) for item in results if item.get("case_id")]
    missing_required_cases = [
        required_case
        for required_case in required
        if not _case_requirement_satisfied(required_case, case_ids)
    ]
    case_checks = _minimum_case_checks(results) if require_minimum_set else []
    case_check_fail_count = sum(1 for item in case_checks if item.get("result") != "pass")
    legacy_oracle_evidence_checks = (
        _legacy_oracle_evidence_checks(results) if require_legacy_evidence else []
    )
    legacy_oracle_evidence_fail_count = sum(
        1 for item in legacy_oracle_evidence_checks if item.get("result") != "pass"
    )
    fail_count = sum(1 for item in results if not item.get("match"))
    oracle_kind_counts = _oracle_kind_counts(results)
    errors: list[str] = []
    if not results:
        errors.append("No acceptance records found")
    if require_legacy_oracle and not oracle_kind_counts.get("legacy_oracle"):
        errors.append("No legacy_oracle acceptance records found")
    if legacy_oracle_evidence_fail_count:
        errors.append("Legacy oracle evidence incomplete")
    match = (
        not errors
        and fail_count == 0
        and not missing_required_cases
        and case_check_fail_count == 0
        and legacy_oracle_evidence_fail_count == 0
    )
    return {
        "schema": ACCEPTANCE_SUITE_SCHEMA,
        "suite_path": str(path),
        "record_count": len(results),
        "pass_count": len(results) - fail_count,
        "fail_count": fail_count,
        "case_check_fail_count": case_check_fail_count,
        "legacy_oracle_evidence_fail_count": legacy_oracle_evidence_fail_count,
        "oracle_kind_counts": oracle_kind_counts,
        "required_cases": required,
        "missing_required_cases": missing_required_cases,
        "case_checks": case_checks,
        "legacy_oracle_evidence_checks": legacy_oracle_evidence_checks,
        "errors": errors,
        "match": match,
        "result": "pass" if match else "fail",
        "records": results,
    }


def parse_whitelist_args(values: list[str] | None) -> list[dict[str, str]]:
    return _parse_path_reason_args(values)


def parse_intentional_difference_args(values: list[str] | None) -> list[dict[str, str]]:
    return _parse_path_reason_args(values)


def _parse_path_reason_args(values: list[str] | None) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for value in values or []:
        path, separator, reason = value.partition("=")
        path = path.strip()
        if not path:
            continue
        entries.append({"path": path, "reason": reason.strip() if separator else ""})
    return entries


def _normalize_path_reason_entries(values: list[dict[str, str]] | None) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for value in values or []:
        if not isinstance(value, dict):
            continue
        path = str(value.get("path") or "").strip()
        if not path:
            continue
        entries.append({"path": path, "reason": str(value.get("reason") or "").strip()})
    return entries


def _record_intentional_differences(record: dict[str, Any]) -> list[dict[str, str]]:
    value = record.get("intentional_differences")
    if value is None:
        value = (record.get("diff") or {}).get("intentional_differences")
    return _normalize_path_reason_entries(value if isinstance(value, list) else [])


def _record_oracle_kind(record: dict[str, Any]) -> str:
    return _normalize_oracle_kind(record.get("oracle_kind") or DEFAULT_ACCEPTANCE_ORACLE_KIND)


def _normalize_oracle_kind(value: str | None) -> str:
    text = str(value or DEFAULT_ACCEPTANCE_ORACLE_KIND).strip()
    if text not in ACCEPTANCE_ORACLE_KINDS:
        raise ValueError(
            f"Unsupported acceptance oracle_kind: {value!r}; expected one of {ACCEPTANCE_ORACLE_KINDS}"
        )
    return text


def _oracle_kind_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        kind = str(record.get("oracle_kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _legacy_oracle_evidence_checks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _legacy_oracle_evidence_check(record)
        for record in records
        if record.get("oracle_kind") == "legacy_oracle"
    ]


def _legacy_oracle_evidence_check(record: dict[str, Any]) -> dict[str, Any]:
    messages: list[str] = []
    image_evidence = (
        record.get("image_evidence")
        if isinstance(record.get("image_evidence"), dict)
        else {}
    )
    _append_image_evidence_messages(
        messages,
        image_evidence.get("legacy"),
        label="legacy image",
    )
    _append_image_evidence_messages(
        messages,
        image_evidence.get("core"),
        label="core image",
    )
    _append_generation_result_evidence_messages(
        messages,
        record.get("generation_result_evidence"),
    )
    _append_prompt_bundle_evidence_messages(
        messages,
        record.get("prompt_bundle_contract_evidence"),
    )
    return {
        "case_id": str(record.get("case_id") or ""),
        "record_path": str(record.get("record_path") or ""),
        "result": "pass" if not messages else "fail",
        "messages": messages,
    }


def _append_image_evidence_messages(
    messages: list[str],
    evidence: Any,
    *,
    label: str,
) -> None:
    if not isinstance(evidence, dict):
        messages.append(f"missing {label} evidence")
        return
    if not evidence.get("exists"):
        messages.append(f"{label} does not exist")
        return
    if not evidence.get("sha256"):
        messages.append(f"{label} missing sha256")
    if evidence.get("png_error"):
        messages.append(f"{label} PNG parameters unreadable: {evidence['png_error']}")
        return
    png_info = evidence.get("png_info")
    if not isinstance(png_info, dict) or not png_info.get("parameters"):
        messages.append(f"{label} missing PNG parameters")


def _append_generation_result_evidence_messages(messages: list[str], evidence: Any) -> None:
    if not isinstance(evidence, dict):
        messages.append("missing GenerationResult evidence")
        return
    if evidence.get("result") != "pass":
        messages.append("GenerationResult evidence failed")
    if not evidence.get("image_count"):
        messages.append("GenerationResult has no archived images")
    _append_generation_result_png_info_messages(messages, evidence)


def _append_generation_result_png_info_messages(
    messages: list[str],
    evidence: dict[str, Any],
) -> None:
    png_info = evidence.get("png_info")
    png_images = png_info.get("images") if isinstance(png_info, dict) else None
    if not isinstance(png_images, list):
        messages.append("GenerationResult missing png_info image evidence")
        return
    if evidence.get("image_count") and not png_images:
        messages.append("GenerationResult has no png_info image evidence")
        return
    for index, item in enumerate(png_images):
        if not isinstance(item, dict):
            messages.append(f"GenerationResult png_info image[{index}] evidence invalid")
            continue
        if not item.get("has_parameters") and not item.get("has_error"):
            messages.append(
                f"GenerationResult png_info image[{index}] missing parameters or error"
            )


def _append_prompt_bundle_evidence_messages(messages: list[str], evidence: Any) -> None:
    if not isinstance(evidence, dict):
        messages.append("missing PromptBundle contract evidence")
        return
    if evidence.get("result") != "pass":
        messages.append("PromptBundle contract evidence failed")


def _legacy_record_paths(*, source: Path, image: Path | None) -> dict[str, str]:
    data = {"source_path": str(source)}
    if image is not None:
        data["image_path"] = str(image)
    if source.suffix.lower() == ".png":
        data.setdefault("image_path", str(source))
    else:
        data["params_path"] = str(source)
    return data


def _effective_image_path(source: Path, image: str | Path | None) -> Path | None:
    if image is not None:
        return Path(image)
    if source.suffix.lower() == ".png":
        return source
    return None


def _image_evidence(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    evidence: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
    }
    if not path.exists():
        return evidence
    if not path.is_file():
        evidence["error"] = "Not a file"
        return evidence

    evidence["bytes"] = path.stat().st_size
    evidence["sha256"] = _file_sha256(path)
    try:
        evidence["png_info"] = read_image_parameters(path)
    except Exception as exc:  # 旧图或后端输出可能不是 PNG，保留错误便于验收判断。
        evidence["png_error"] = str(exc)
    return evidence


def _generation_result_evidence(
    path: Path | None,
    *,
    core_data: dict[str, Any],
) -> dict[str, Any] | None:
    if path is None:
        return None

    evidence: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "result": "fail",
        "errors": [],
    }
    errors: list[str] = evidence["errors"]
    if not path.exists():
        errors.append("GenerationResult file does not exist")
        return evidence
    if not path.is_file():
        errors.append("GenerationResult path is not a file")
        return evidence

    try:
        data = _load_json_mapping(path)
    except Exception as exc:
        errors.append(f"Unable to read GenerationResult JSON: {exc}")
        return evidence

    evidence["schema"] = data.get("schema")
    evidence["backend"] = data.get("backend")
    evidence["cache_hit"] = data.get("cache_hit")
    images = data.get("images")
    evidence["image_count"] = len(images) if isinstance(images, list) else 0
    image_summaries, image_errors = _generation_result_image_summaries(
        images,
        base_dir=path.parent,
    )
    evidence["images"] = image_summaries
    errors.extend(image_errors)
    png_info = data.get("png_info")
    png_info_summary, png_info_errors = _generation_result_png_info_summary(
        png_info,
        image_summaries=image_summaries,
        base_dir=path.parent,
    )
    if png_info_summary is not None:
        evidence["png_info"] = png_info_summary
    errors.extend(png_info_errors)

    request_body = data.get("request_body")
    if not isinstance(request_body, dict) or not request_body:
        errors.append("GenerationResult missing request_body")
    else:
        diffs = [
            diff.as_dict()
            for diff in compare_render_parameters(core_data, request_body)
        ]
        evidence["request_body"] = {
            "normalized": normalize_render_parameters(request_body),
            "diff": {
                "normalized_equal": not diffs,
                "diff_count": len(diffs),
                "diffs": diffs,
            },
        }
        if diffs:
            errors.append("GenerationResult request_body differs from core source")

    evidence["result"] = "pass" if not errors else "fail"
    return evidence


def _generation_result_image_summaries(
    value: Any,
    *,
    base_dir: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(value, list):
        if value is None:
            return [], []
        return [], ["GenerationResult images must be a list"]
    summaries: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"GenerationResult image[{index}] must be an object")
            continue
        raw_path = item.get("path")
        path = _resolve_generation_result_image_path(raw_path, base_dir)
        summary: dict[str, Any] = {
            "path": raw_path,
            "filename": item.get("filename"),
            "meta": item.get("meta") if isinstance(item.get("meta"), dict) else {},
        }
        if path is None:
            summary["exists"] = False
            errors.append(f"GenerationResult image[{index}] missing path")
            summaries.append(summary)
            continue

        summary["resolved_path"] = str(path)
        summary["exists"] = path.exists()
        if not path.exists():
            errors.append(f"GenerationResult image[{index}] does not exist: {path}")
        elif not path.is_file():
            summary["error"] = "Not a file"
            errors.append(f"GenerationResult image[{index}] is not a file: {path}")
        else:
            summary["bytes"] = path.stat().st_size
            summary["sha256"] = _file_sha256(path)
        summaries.append(summary)
    return summaries, errors


def _generation_result_png_info_summary(
    value: Any,
    *,
    image_summaries: list[dict[str, Any]],
    base_dir: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(value, dict):
        if image_summaries:
            return None, ["GenerationResult missing png_info.images"]
        return None, []

    summary: dict[str, Any] = {
        "keys": sorted(str(key) for key in value.keys()),
        "image_count": 0,
    }
    png_images = value.get("images")
    if not isinstance(png_images, list):
        if image_summaries:
            return summary, ["GenerationResult png_info.images must be a list"]
        return summary, []

    summary["image_count"] = len(png_images)
    image_items, errors = _generation_result_png_info_image_summaries(
        png_images,
        image_summaries=image_summaries,
        base_dir=base_dir,
    )
    summary["images"] = image_items
    if len(png_images) != len(image_summaries):
        errors.append(
            "GenerationResult png_info.images length differs from images length"
        )
    return summary, errors


def _generation_result_png_info_image_summaries(
    value: list[Any],
    *,
    image_summaries: list[dict[str, Any]],
    base_dir: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    summaries: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"GenerationResult png_info image[{index}] must be an object")
            continue
        raw_path = item.get("path")
        path = _resolve_generation_result_image_path(raw_path, base_dir)
        item_parameters = item.get("parameters")
        item_error = item.get("error")
        summary: dict[str, Any] = {
            "path": raw_path,
            "has_parameters": bool(item_parameters),
            "has_error": bool(item_error),
        }
        if item_parameters is not None and not isinstance(item_parameters, dict):
            errors.append(
                f"GenerationResult png_info image[{index}] parameters must be an object"
            )
        if item_parameters is not None and item_error is not None:
            errors.append(
                f"GenerationResult png_info image[{index}] has both parameters and error"
            )
        if item_error is not None and (
            not isinstance(item_error, str) or not item_error.strip()
        ):
            errors.append(
                f"GenerationResult png_info image[{index}] error must be a non-empty string"
            )
        if path is None:
            errors.append(f"GenerationResult png_info image[{index}] missing path")
        else:
            summary["resolved_path"] = str(path)
            expected = (
                image_summaries[index].get("resolved_path")
                if index < len(image_summaries)
                else None
            )
            if expected is not None and not _same_path(path, Path(str(expected))):
                errors.append(
                    f"GenerationResult png_info image[{index}] path differs from images[{index}]"
                )
            if isinstance(item_parameters, dict):
                _append_generation_result_png_parameter_evidence(
                    summary,
                    errors,
                    index=index,
                    path=path,
                    parameters=item_parameters,
                )
            if isinstance(item_error, str) and item_error.strip():
                _append_generation_result_png_error_evidence(
                    summary,
                    errors,
                    index=index,
                    path=path,
                )
        summaries.append(summary)
    return summaries, errors


def _append_generation_result_png_parameter_evidence(
    summary: dict[str, Any],
    errors: list[str],
    *,
    index: int,
    path: Path,
    parameters: dict[str, Any],
) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        image_parameters = read_image_parameters(path)
    except Exception as exc:
        summary["parameter_check"] = {"result": "fail", "error": str(exc)}
        errors.append(
            f"GenerationResult png_info image[{index}] parameters unreadable from image"
        )
        return
    diffs = [
        diff.as_dict()
        for diff in compare_render_parameters(
            {"parameters": parameters},
            image_parameters,
        )
    ]
    summary["parameter_check"] = {
        "result": "pass" if not diffs else "fail",
        "diff_count": len(diffs),
        "diffs": diffs,
    }
    if diffs:
        errors.append(
            f"GenerationResult png_info image[{index}] parameters differ from image PNG"
        )


def _append_generation_result_png_error_evidence(
    summary: dict[str, Any],
    errors: list[str],
    *,
    index: int,
    path: Path,
) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        read_image_parameters(path)
    except Exception as exc:
        summary["error_check"] = {"result": "pass", "actual_error": str(exc)}
        return
    summary["error_check"] = {"result": "fail"}
    errors.append(
        f"GenerationResult png_info image[{index}] error contradicts readable PNG"
    )


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _resolve_generation_result_image_path(value: Any, base_dir: Path) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else base_dir / path


def _rewrite_generation_result_image_paths(
    path: Path | None,
    *,
    source_generation_result: Path | None,
    source_core_image: Path | None,
    archived_core_image: Path | None,
) -> None:
    if path is None or archived_core_image is None or not path.is_file():
        return

    try:
        data = _load_json_mapping(path)
    except Exception:
        return

    source_base = source_generation_result.parent if source_generation_result else path.parent
    relative_archived_image = _relative_path_string(str(archived_core_image), path.parent)
    changed = False

    images = data.get("images")
    if isinstance(images, list):
        for item in images:
            if not isinstance(item, dict):
                continue
            if _generation_result_image_matches(item, source_base, source_core_image):
                item["path"] = relative_archived_image
                item["filename"] = item.get("filename") or archived_core_image.name
                changed = True

    png_info = data.get("png_info")
    if isinstance(png_info, dict) and isinstance(png_info.get("images"), list):
        for item in png_info["images"]:
            if not isinstance(item, dict):
                continue
            if _generation_result_image_matches(item, source_base, source_core_image):
                item["path"] = relative_archived_image
                changed = True

    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _generation_result_source_core_image(
    core_image: str | Path | None,
    core_source: str | Path,
) -> Path | None:
    if core_image:
        return Path(core_image)
    core_source_path = Path(core_source)
    return core_source_path if _is_png_path(core_source_path) else None


def _generation_result_image_matches(
    item: dict[str, Any],
    source_base: Path,
    source_core_image: Path | None,
) -> bool:
    if source_core_image is None:
        return False
    raw_path = item.get("path")
    if raw_path is None:
        return False
    path = Path(str(raw_path))
    resolved = path if path.is_absolute() else source_base / path
    try:
        return resolved.resolve() == source_core_image.resolve()
    except OSError:
        return False


def _generation_result_evidence_pass(record: dict[str, Any]) -> bool:
    evidence = record.get("generation_result_evidence")
    return evidence is None or evidence.get("result") == "pass"


def _prompt_bundle_contract_evidence_pass(record: dict[str, Any]) -> bool:
    evidence = record.get("prompt_bundle_contract_evidence")
    return evidence is None or evidence.get("result") == "pass"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _core_record_paths(
    *,
    source: Path,
    image: Path | None,
    prompt_bundle: Path | None,
    generation_result: Path | None,
) -> dict[str, str]:
    data = {"source_path": str(source)}
    if image is not None:
        data["image_path"] = str(image)
    if source.suffix.lower() == ".png":
        data.setdefault("image_path", str(source))
    else:
        data["render_request_path"] = str(source)
    if prompt_bundle is not None:
        data["prompt_bundle_path"] = str(prompt_bundle)
    if generation_result is not None:
        data["generation_result_path"] = str(generation_result)
    return data


def _load_composition(
    *,
    core_data: dict[str, Any],
    prompt_bundle: Path | None,
) -> dict[str, Any]:
    if prompt_bundle is not None:
        bundle_data = _load_json_mapping(prompt_bundle)
        composition = ((bundle_data.get("meta") or {}).get("composition") or {})
        if isinstance(composition, dict):
            return composition
    composition = ((core_data.get("meta") or {}).get("composition") or {})
    return composition if isinstance(composition, dict) else {}


def _prompt_bundle_contract_evidence(prompt_bundle: Path | None) -> dict[str, Any] | None:
    if prompt_bundle is None:
        return None
    bundle_data = _load_json_mapping(prompt_bundle)
    meta = bundle_data.get("meta") if isinstance(bundle_data.get("meta"), dict) else {}
    forbidden = [
        key
        for key in ("shot", "constraints")
        if key in meta
    ]
    return {
        "path": str(prompt_bundle),
        "forbidden_meta_fields": forbidden,
        "result": "fail" if forbidden else "pass",
    }


def _load_json_mapping(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _record_source(record: dict[str, Any], side: str) -> str:
    data = record.get(side)
    if not isinstance(data, dict):
        raise ValueError(f"Acceptance record missing {side} section")
    source = (
        data.get("source_path")
        or data.get("params_path")
        or data.get("render_request_path")
        or data.get("image_path")
    )
    if not source:
        raise ValueError(f"Acceptance record missing {side} source path")
    return str(source)


def _suite_record_paths(path: Path) -> tuple[list[Path], list[str]]:
    if path.is_dir():
        return _discover_record_paths(path), []

    manifest = load_acceptance_record(path)
    if manifest.get("schema") == ACCEPTANCE_SCHEMA:
        return [path], []

    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError(f"Acceptance suite manifest must contain records list: {path}")
    record_paths = [_resolve_manifest_record(entry, path.parent) for entry in records]
    required_cases = manifest.get("required_cases") or []
    if not isinstance(required_cases, list):
        raise ValueError(f"Acceptance suite required_cases must be a list: {path}")
    return record_paths, [str(item) for item in required_cases if str(item).strip()]


def _discover_record_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file() or candidate.suffix.lower() not in ACCEPTANCE_RECORD_EXTENSIONS:
            continue
        try:
            data = load_acceptance_record(candidate)
        except Exception:
            continue
        if data.get("schema") == ACCEPTANCE_SCHEMA:
            paths.append(candidate)
    return paths


def _resolve_manifest_record(entry: Any, base_dir: Path) -> Path:
    if isinstance(entry, str):
        return _resolve_record_path(entry, base_dir)
    if isinstance(entry, dict):
        value = entry.get("path") or entry.get("record_path")
        if value:
            return _resolve_record_path(str(value), base_dir)
    raise ValueError(f"Invalid acceptance suite record entry: {entry!r}")


def _optional_record_path(value: str | Path | None, base_dir: Path) -> Path | None:
    if value is None:
        return None
    return _resolve_record_path(value, base_dir)


def _resolve_record_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path


def _unique_strings(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _case_requirement_satisfied(required_case: str, case_ids: list[str]) -> bool:
    prefix = f"{required_case}_"
    return any(case_id == required_case or case_id.startswith(prefix) for case_id in case_ids)


def _minimum_case_checks(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for required_case in MINIMUM_ACCEPTANCE_CASES:
        records = _records_for_required_case(required_case, results)
        if not records:
            continue
        if required_case == "default_action":
            checks.append(_default_action_case_check(records))
        elif required_case in MINIMUM_SCOPE_CASES:
            checks.append(_scope_case_check(required_case, records))
        elif required_case == "complex_character":
            checks.append(_complex_character_case_check(records))
        elif required_case == "reference_style":
            checks.append(_reference_style_case_check(records))
    return checks


def _records_for_required_case(
    required_case: str,
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        record
        for record in results
        if _case_requirement_satisfied(required_case, [str(record.get("case_id") or "")])
    ]


def _scope_case_check(required_case: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    rule = MINIMUM_SCOPE_CASES[required_case]
    failures: list[str] = []
    for record in records:
        errors = _scope_case_errors(record, rule)
        if not errors:
            return {
                "required_case": required_case,
                "case_ids": [str(item.get("case_id")) for item in records],
                "matched_case_id": str(record.get("case_id")),
                "result": "pass",
                "messages": [],
            }
        failures.append(f"{record.get('case_id')}: {'; '.join(errors)}")
    return {
        "required_case": required_case,
        "case_ids": [str(item.get("case_id")) for item in records],
        "matched_case_id": None,
        "result": "fail",
        "messages": failures,
    }


def _scope_case_errors(record: dict[str, Any], rule: dict[str, Any]) -> list[str]:
    composition = record.get("composition") if isinstance(record.get("composition"), dict) else {}
    included = set(_normalized_string_list(composition.get("included_character_sections")))
    suppressed = set(_normalized_string_list(composition.get("suppressed_character_sections")))
    expected_scope = str(rule["character_scope"])
    errors: list[str] = []
    if composition.get("character_scope") != expected_scope:
        errors.append(f"expected character_scope={expected_scope}")
    included_any = set(rule["included_any"])
    if included.isdisjoint(included_any):
        errors.append(f"expected one included section from {sorted(included_any)}")
    missing_suppressed = sorted(set(rule["suppressed_all"]) - suppressed)
    if missing_suppressed:
        errors.append(f"missing suppressed sections {missing_suppressed}")
    forbidden_terms = _suppressed_prompt_terms(suppressed)
    prompt = _normalized_core_prompt(record)
    found_forbidden_terms = _terms_in_prompt(prompt, forbidden_terms)
    if found_forbidden_terms:
        errors.append(f"prompt contains suppressed section terms {found_forbidden_terms}")
    return errors


def _default_action_case_check(records: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    for record in records:
        errors = _default_action_case_errors(record)
        if not errors:
            return {
                "required_case": "default_action",
                "case_ids": [str(item.get("case_id")) for item in records],
                "matched_case_id": str(record.get("case_id")),
                "result": "pass",
                "messages": [],
            }
        failures.append(f"{record.get('case_id')}: {'; '.join(errors)}")
    return {
        "required_case": "default_action",
        "case_ids": [str(item.get("case_id")) for item in records],
        "matched_case_id": None,
        "result": "fail",
        "messages": failures,
    }


def _default_action_case_errors(record: dict[str, Any]) -> list[str]:
    params = _normalized_core_parameters(record)
    if not isinstance(params, dict):
        return ["missing normalized core parameters"]

    errors: list[str] = []
    missing_params = [
        key for key in MINIMUM_DEFAULT_ACTION_REQUIRED_PARAMS if key not in params
    ]
    if missing_params:
        errors.append(f"missing core parameters {missing_params}")

    for key in MINIMUM_DEFAULT_ACTION_EMPTY_ARRAY_PARAMS:
        if key not in params:
            continue
        value = params.get(key)
        if not isinstance(value, list):
            errors.append(f"{key} must be an array")
        elif value:
            errors.append(f"{key} must be empty for default_action")

    for key in ("v4_prompt", "v4_negative_prompt"):
        value = params.get(key)
        if not isinstance(value, dict):
            errors.append(f"{key} must be an object")
            continue
        caption = value.get("caption")
        if not isinstance(caption, dict) or "base_caption" not in caption:
            errors.append(f"{key}.caption.base_caption missing")
    return errors


def _complex_character_case_check(records: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    for record in records:
        errors = _complex_character_case_errors(record)
        if not errors:
            return {
                "required_case": "complex_character",
                "case_ids": [str(item.get("case_id")) for item in records],
                "matched_case_id": str(record.get("case_id")),
                "result": "pass",
                "messages": [],
            }
        failures.append(f"{record.get('case_id')}: {'; '.join(errors)}")
    return {
        "required_case": "complex_character",
        "case_ids": [str(item.get("case_id")) for item in records],
        "matched_case_id": None,
        "result": "fail",
        "messages": failures,
    }


def _complex_character_case_errors(record: dict[str, Any]) -> list[str]:
    composition = record.get("composition") if isinstance(record.get("composition"), dict) else {}
    included = set(_normalized_string_list(composition.get("included_character_sections")))
    suppressed = set(_normalized_string_list(composition.get("suppressed_character_sections")))
    required = set(MINIMUM_COMPLEX_CHARACTER_REQUIRED_INCLUDED)
    errors: list[str] = []
    missing_included = sorted(required - included)
    if missing_included:
        errors.append(f"missing included sections {missing_included}")
    incorrectly_suppressed = sorted(required & suppressed)
    if incorrectly_suppressed:
        errors.append(f"unexpected suppressed sections {incorrectly_suppressed}")
    return errors


def _reference_style_case_check(records: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    for record in records:
        errors = _reference_style_case_errors(record)
        if not errors:
            return {
                "required_case": "reference_style",
                "case_ids": [str(item.get("case_id")) for item in records],
                "matched_case_id": str(record.get("case_id")),
                "result": "pass",
                "messages": [],
            }
        failures.append(f"{record.get('case_id')}: {'; '.join(errors)}")
    return {
        "required_case": "reference_style",
        "case_ids": [str(item.get("case_id")) for item in records],
        "matched_case_id": None,
        "result": "fail",
        "messages": failures,
    }


def _reference_style_case_errors(record: dict[str, Any]) -> list[str]:
    params = _normalized_core_parameters(record)
    if not isinstance(params, dict):
        return ["missing normalized core parameters"]
    references = params.get("reference_image_multiple") or []
    strengths = params.get("reference_strength_multiple") or []
    information = params.get("reference_information_extracted_multiple") or []
    director_references = params.get("director_reference_images") or []
    errors: list[str] = []
    if not isinstance(references, list) or not references:
        errors.append("missing reference_image_multiple")
    if not isinstance(strengths, list) or len(strengths) != len(references):
        errors.append("reference_strength_multiple length mismatch")
    if not isinstance(information, list) or len(information) != len(references):
        errors.append("reference_information_extracted_multiple length mismatch")
    if not isinstance(director_references, list) or not director_references:
        errors.append("missing director_reference_images")
    return errors


def _normalized_core_parameters(record: dict[str, Any]) -> dict[str, Any] | None:
    normalized = record.get("normalized")
    if not isinstance(normalized, dict):
        return None
    core = normalized.get("core")
    if not isinstance(core, dict):
        return None
    params = core.get("parameters")
    return params if isinstance(params, dict) else None


def _normalized_core_prompt(record: dict[str, Any]) -> str:
    params = _normalized_core_parameters(record)
    if isinstance(params, dict) and isinstance(params.get("prompt"), str):
        return params["prompt"]

    normalized = record.get("normalized")
    if not isinstance(normalized, dict):
        return ""
    core = normalized.get("core")
    if not isinstance(core, dict):
        return ""
    return str(core.get("input") or "")


def _suppressed_prompt_terms(suppressed_sections: set[str]) -> list[str]:
    terms: list[str] = []
    for section in sorted(suppressed_sections):
        terms.extend(MINIMUM_SUPPRESSED_SECTION_PROMPT_TERMS.get(section, ()))
    return _unique_strings(terms)


def _terms_in_prompt(prompt: str, terms: list[str]) -> list[str]:
    normalized_prompt = prompt.lower()
    return [
        term
        for term in terms
        if re.search(
            rf"(?<![a-z0-9_]){re.escape(term.lower())}(?![a-z0-9_])",
            normalized_prompt,
        )
    ]


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _validate_case_id(case_id: str) -> str:
    value = str(case_id).strip()
    if not value:
        raise ValueError("case_id must not be empty")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"case_id must be a plain directory name: {case_id!r}")
    return value


def _artifact_filename(prefix: str, source: str | Path) -> str:
    suffix = Path(source).suffix or ".json"
    return f"{prefix}{suffix}"


def _copy_acceptance_artifact(
    source: str | Path,
    target_dir: Path,
    filename: str,
    *,
    overwrite: bool,
) -> Path:
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"Acceptance artifact not found: {source_path}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    if source_path.resolve() == target_path.resolve():
        return target_path
    if target_path.exists() and not overwrite:
        raise FileExistsError(
            f"Acceptance artifact already exists, pass --overwrite to replace: {target_path}"
        )
    shutil.copy2(source_path, target_path)
    return target_path


def _copy_optional_acceptance_artifact(
    source: str | Path | None,
    target_dir: Path,
    filename: str | None,
    *,
    overwrite: bool,
    fallback: Path | None = None,
) -> Path | None:
    if source is None:
        return fallback
    if filename is None:
        raise ValueError("Optional artifact filename is required when source is provided")
    source_path = Path(source)
    if fallback is not None and source_path.resolve() == fallback.resolve():
        return fallback
    return _copy_acceptance_artifact(
        source_path,
        target_dir,
        filename,
        overwrite=overwrite,
    )


def _is_png_path(path: Path | None) -> bool:
    return path is not None and path.suffix.lower() == ".png"


def _archive_artifacts(**paths: Path | None) -> dict[str, str]:
    return {name: str(path) for name, path in paths.items() if path is not None}


def _record_suffix(record_format: str) -> str:
    if record_format == "auto":
        return "yaml"
    if record_format in {"yaml", "yml"}:
        return "yaml"
    if record_format == "json":
        return "json"
    raise ValueError(f"Unsupported acceptance record format: {record_format}")


def _write_acceptance_document(
    data: dict[str, Any],
    path: Path,
    *,
    output_format: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    format_name = output_format
    if format_name == "auto":
        format_name = "yaml" if path.suffix.lower() in {".yaml", ".yml"} else "json"
    if format_name in {"yaml", "yml"}:
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return
    if format_name == "json":
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    raise ValueError(f"Unsupported acceptance document format: {output_format}")


def _relativize_acceptance_record_paths(
    record: dict[str, Any],
    base_dir: Path,
) -> dict[str, Any]:
    return _relativize_path_fields(record, base_dir)


def _relativize_path_fields(value: Any, base_dir: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: _relative_path_string(item, base_dir)
            if key in ACCEPTANCE_PATH_FIELDS or (key == "path" and _looks_like_file_path(item))
            else _relativize_path_fields(item, base_dir)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_relativize_path_fields(item, base_dir) for item in value]
    return value


def _relative_path_string(value: Any, base_dir: Path) -> Any:
    if not isinstance(value, str):
        return value
    path = Path(value)
    if not path.is_absolute():
        return value.replace("\\", "/")
    try:
        return path.relative_to(base_dir).as_posix()
    except ValueError:
        return value


def _looks_like_file_path(value: Any) -> bool:
    if not isinstance(value, str) or value.startswith("$"):
        return False
    path = Path(value)
    return path.is_absolute() or "/" in value or "\\" in value


def _upsert_acceptance_suite_manifest(
    manifest_path: Path,
    *,
    record_path: Path,
    required_cases: list[str],
) -> None:
    if manifest_path.exists():
        manifest = load_acceptance_record(manifest_path)
    else:
        manifest = {
            "schema": ACCEPTANCE_SUITE_MANIFEST_SCHEMA,
            "required_cases": [],
            "records": [],
        }

    manifest["schema"] = manifest.get("schema") or ACCEPTANCE_SUITE_MANIFEST_SCHEMA
    existing_required = manifest.get("required_cases") or []
    if not isinstance(existing_required, list):
        raise ValueError(f"Acceptance suite required_cases must be a list: {manifest_path}")
    manifest["required_cases"] = _unique_strings([*existing_required, *required_cases])

    existing_records = manifest.get("records") or []
    if not isinstance(existing_records, list):
        raise ValueError(f"Acceptance suite records must be a list: {manifest_path}")
    relative_record = _manifest_record_path(record_path, manifest_path.parent)
    existing_record_paths = {
        str(_manifest_entry_path(entry)).replace("\\", "/")
        for entry in existing_records
        if _manifest_entry_path(entry)
    }
    if relative_record not in existing_record_paths:
        existing_records.append(relative_record)
    manifest["records"] = existing_records

    _write_acceptance_document(
        manifest,
        manifest_path,
        output_format="yaml" if manifest_path.suffix.lower() in {".yaml", ".yml"} else "json",
    )


def _manifest_record_path(record_path: Path, base_dir: Path) -> str:
    try:
        return record_path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return str(record_path)


def _manifest_entry_path(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        value = entry.get("path") or entry.get("record_path")
        return str(value) if value else None
    return None
