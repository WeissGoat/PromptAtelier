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


def build_acceptance_record(
    *,
    case_id: str,
    legacy_source: str | Path,
    core_source: str | Path,
    legacy_image: str | Path | None = None,
    core_image: str | Path | None = None,
    prompt_bundle: str | Path | None = None,
    whitelist: list[dict[str, str]] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    legacy_source_path = Path(legacy_source)
    core_source_path = Path(core_source)
    legacy_data = load_render_parameter_source(legacy_source_path)
    core_data = load_render_parameter_source(core_source_path)
    diffs = [diff.as_dict() for diff in compare_render_parameters(legacy_data, core_data)]
    whitelist = whitelist or []
    approved_paths = {entry["path"] for entry in whitelist if entry.get("path")}
    unapproved_diffs = [diff for diff in diffs if diff["path"] not in approved_paths]

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
            "unapproved_diff_count": len(unapproved_diffs),
            "diffs": diffs,
            "unapproved_diffs": unapproved_diffs,
            "whitelist": whitelist,
        },
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

    rebuilt = build_acceptance_record(
        case_id=str(record.get("case_id") or path.stem),
        legacy_source=_record_source(record, "legacy"),
        core_source=_record_source(record, "core"),
        legacy_image=(record.get("legacy") or {}).get("image_path"),
        core_image=(record.get("core") or {}).get("image_path"),
        prompt_bundle=(record.get("core") or {}).get("prompt_bundle_path"),
        whitelist=(record.get("diff") or {}).get("whitelist") or [],
        notes=record.get("notes") or [],
    )
    return {
        "schema": "tags-machine-core.acceptance-verification/v1",
        "record_path": str(path),
        "case_id": rebuilt["case_id"],
        "match": rebuilt["result"] == "pass",
        "result": rebuilt["result"],
        "diff": rebuilt["diff"],
        "composition": rebuilt["composition"],
    }


def parse_whitelist_args(values: list[str] | None) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for value in values or []:
        path, separator, reason = value.partition("=")
        path = path.strip()
        if not path:
            continue
        entries.append({"path": path, "reason": reason.strip() if separator else ""})
    return entries


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
