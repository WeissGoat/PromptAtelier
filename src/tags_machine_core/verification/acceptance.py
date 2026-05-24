from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.contracts import utc_now_iso
from tags_machine_core.verification.render_params import (
    compare_render_parameters,
    load_render_parameter_source,
    normalize_render_parameters,
)


ACCEPTANCE_SCHEMA = "tags-machine-core.acceptance-record/v1"
ACCEPTANCE_SUITE_SCHEMA = "tags-machine-core.acceptance-suite-verification/v1"
MINIMUM_ACCEPTANCE_CASES = (
    "default_action",
    "foot_detail",
    "hand_detail",
    "complex_character",
    "reference_style",
)
ACCEPTANCE_RECORD_EXTENSIONS = {".json", ".yaml", ".yml"}


def build_acceptance_record(
    *,
    case_id: str,
    legacy_source: str | Path,
    core_source: str | Path,
    legacy_image: str | Path | None = None,
    core_image: str | Path | None = None,
    prompt_bundle: str | Path | None = None,
    whitelist: list[dict[str, str]] | None = None,
    intentional_differences: list[dict[str, str]] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    legacy_source_path = Path(legacy_source)
    core_source_path = Path(core_source)
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
        "legacy": _legacy_record_paths(
            source=legacy_source_path,
            image=Path(legacy_image) if legacy_image else None,
        ),
        "core": _core_record_paths(
            source=core_source_path,
            image=Path(core_image) if core_image else None,
            prompt_bundle=Path(prompt_bundle) if prompt_bundle else None,
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
        "notes": notes or [],
    }
    record["result"] = "pass" if not unapproved_diffs else "fail"
    return record


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
        whitelist=(record.get("diff") or {}).get("whitelist") or [],
        intentional_differences=_record_intentional_differences(record),
        notes=record.get("notes") or [],
    )
    return {
        "schema": "tags-machine-core.acceptance-verification/v1",
        "record_path": str(path),
        "case_id": rebuilt["case_id"],
        "match": rebuilt["result"] == "pass",
        "result": rebuilt["result"],
        "diff": rebuilt["diff"],
        "intentional_differences": rebuilt["intentional_differences"],
        "composition": rebuilt["composition"],
    }


def verify_acceptance_suite(
    path: str | Path,
    *,
    required_cases: list[str] | None = None,
    require_minimum_set: bool = False,
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
    fail_count = sum(1 for item in results if not item.get("match"))
    errors: list[str] = []
    if not results:
        errors.append("No acceptance records found")
    match = not errors and fail_count == 0 and not missing_required_cases
    return {
        "schema": ACCEPTANCE_SUITE_SCHEMA,
        "suite_path": str(path),
        "record_count": len(results),
        "pass_count": len(results) - fail_count,
        "fail_count": fail_count,
        "required_cases": required,
        "missing_required_cases": missing_required_cases,
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


def _legacy_record_paths(*, source: Path, image: Path | None) -> dict[str, str]:
    data = {"source_path": str(source)}
    if image is not None:
        data["image_path"] = str(image)
    if source.suffix.lower() == ".png":
        data.setdefault("image_path", str(source))
    else:
        data["params_path"] = str(source)
    return data


def _core_record_paths(
    *,
    source: Path,
    image: Path | None,
    prompt_bundle: Path | None,
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
