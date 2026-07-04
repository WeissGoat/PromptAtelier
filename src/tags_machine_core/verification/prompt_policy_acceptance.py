from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.verification.compare_report import VISUAL_RESULTS
from tags_machine_core.verification.image_params import (
    read_image_parameters,
    read_png_dimensions,
)
from tags_machine_core.verification.render_params import (
    compare_render_parameters,
    normalize_render_parameters,
)


PROMPT_POLICY_ACCEPTANCE_SCHEMA = "tags-machine-core.prompt-policy-acceptance/v1"
GENERATION_RESULT_SCHEMA = "tags-machine-core.generation-result/v1"
PROMPT_BUNDLE_SCHEMA = "tags-machine-core.prompt-bundle/v2"


def build_prompt_policy_acceptance_report(
    *,
    legacy_image: str | Path,
    core_run_result: str | Path | None = None,
    core_generation_result: str | Path | None = None,
    prompt_bundle: str | Path | None = None,
    core_image: str | Path | None = None,
    visual_result: str = "pending",
    visual_notes: list[str] | None = None,
    whitelist: list[dict[str, str]] | None = None,
    intentional_differences: list[dict[str, str]] | None = None,
    expected_profile: str | None = None,
    required_rules: list[str] | None = None,
    expect_tokens: list[str] | None = None,
    reject_tokens: list[str] | None = None,
) -> dict[str, Any]:
    """验证 PromptPolicyPipeline 的真实出图对比材料是否满足验收门禁。"""

    visual_result = _normalize_visual_result(visual_result)
    legacy_path = Path(legacy_image)
    run_result_path = Path(core_run_result) if core_run_result else None
    run_result = _load_optional_mapping(run_result_path)
    generation_result, generation_result_source = _resolve_generation_result(
        run_result=run_result,
        run_result_path=run_result_path,
        generation_result_path=Path(core_generation_result) if core_generation_result else None,
    )
    bundle, bundle_source = _resolve_prompt_bundle(
        run_result=run_result,
        run_result_path=run_result_path,
        prompt_bundle_path=Path(prompt_bundle) if prompt_bundle else None,
    )
    core_path = _resolve_core_image_path(
        generation_result,
        source_path=generation_result_source,
        override=Path(core_image) if core_image else None,
    )

    legacy_summary, legacy_params = _image_summary(legacy_path)
    core_summary, core_params = _image_summary(core_path) if core_path else _missing_core_image()
    approved_paths = _approved_paths(whitelist, intentional_differences)
    legacy_core_diff = _diff_summary(
        legacy_params,
        core_params,
        approved_paths=approved_paths,
        missing_message="legacy/core PNG parameters are not comparable",
    )
    request_body = _request_body_from_generation_result(generation_result)
    core_request_vs_png = _diff_summary(
        request_body,
        core_params,
        approved_paths=set(),
        missing_message="GenerationResult request_body and core PNG parameters are not comparable",
    )
    generation_png_info_vs_png = _diff_summary(
        _png_info_parameters_from_generation_result(generation_result),
        core_params,
        approved_paths=set(),
        missing_message="GenerationResult png_info and core PNG parameters are not comparable",
    )
    policy_evidence = _policy_evidence(
        bundle,
        expected_profile=expected_profile,
        required_rules=required_rules or [],
    )
    token_evidence = _token_evidence(
        core_params=core_params,
        expect_tokens=expect_tokens or [],
        reject_tokens=reject_tokens or [],
    )
    visual = {
        "result": visual_result,
        "notes": visual_notes or [],
    }
    checks = {
        "generation_result_schema_valid": generation_result.get("schema") == GENERATION_RESULT_SCHEMA,
        "prompt_bundle_schema_valid": policy_evidence["bundle_schema_valid"],
        "legacy_png_readable": legacy_summary["png_parameters_readable"],
        "core_png_readable": core_summary["png_parameters_readable"],
        "legacy_core_diff_approved": legacy_core_diff["unapproved_diff_count"] == 0,
        "core_request_matches_png": core_request_vs_png["diff_count"] == 0,
        "generation_png_info_matches_png": generation_png_info_vs_png["diff_count"] == 0,
        "policy_enabled": policy_evidence["enabled"],
        "policy_trace_present": policy_evidence["trace_count"] > 0,
        "policy_profile_matches": policy_evidence["profile_matches"],
        "required_rules_present": policy_evidence["required_rules_present"],
        "expected_tokens_present": token_evidence["expected_tokens_present"],
        "rejected_tokens_absent": token_evidence["rejected_tokens_absent"],
        "visual_pass": visual_result == "pass",
    }
    errors = [
        message
        for ok, message in _check_messages(checks, policy_evidence, token_evidence)
        if not ok
    ]
    result = "pass" if not errors else "fail"
    return {
        "schema": PROMPT_POLICY_ACCEPTANCE_SCHEMA,
        "result": result,
        "acceptance_ready": result == "pass",
        "checks": checks,
        "errors": errors,
        "sources": {
            "legacy_image": str(legacy_path),
            "core_run_result": str(run_result_path) if run_result_path else None,
            "core_generation_result": str(generation_result_source) if generation_result_source else None,
            "prompt_bundle": str(bundle_source) if bundle_source else None,
            "core_image": str(core_path) if core_path else None,
        },
        "generation_result": {
            "schema": generation_result.get("schema"),
            "schema_valid": generation_result.get("schema") == GENERATION_RESULT_SCHEMA,
            "backend": generation_result.get("backend"),
        },
        "legacy_image": legacy_summary,
        "core_image": core_summary,
        "legacy_core_parameter_diff": legacy_core_diff,
        "core_request_vs_png": core_request_vs_png,
        "generation_png_info_vs_png": generation_png_info_vs_png,
        "policy": policy_evidence,
        "tokens": token_evidence,
        "visual": visual,
    }


def _load_optional_mapping(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return _load_mapping(path)


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Expected object in {path}")
    return data


def _resolve_generation_result(
    *,
    run_result: dict[str, Any] | None,
    run_result_path: Path | None,
    generation_result_path: Path | None,
) -> tuple[dict[str, Any], Path | None]:
    if generation_result_path is not None:
        data = _load_mapping(generation_result_path)
        if "generation_result" in data and isinstance(data["generation_result"], dict):
            return data["generation_result"], generation_result_path
        return data, generation_result_path
    if run_result is not None:
        generation_result = run_result.get("generation_result")
        if isinstance(generation_result, dict):
            return generation_result, run_result_path
        if run_result.get("schema") == GENERATION_RESULT_SCHEMA:
            return run_result, run_result_path
    raise ValueError("Prompt policy acceptance requires core_run_result or core_generation_result")


def _resolve_prompt_bundle(
    *,
    run_result: dict[str, Any] | None,
    run_result_path: Path | None,
    prompt_bundle_path: Path | None,
) -> tuple[dict[str, Any], Path | None]:
    if prompt_bundle_path is not None:
        return _load_mapping(prompt_bundle_path), prompt_bundle_path
    if run_result is not None and isinstance(run_result.get("prompt_bundle"), dict):
        return run_result["prompt_bundle"], run_result_path
    raise ValueError("Prompt policy acceptance requires prompt_bundle or core_run_result.prompt_bundle")


def _resolve_core_image_path(
    generation_result: dict[str, Any],
    *,
    source_path: Path | None,
    override: Path | None,
) -> Path | None:
    if override is not None:
        return override
    images = generation_result.get("images")
    if not isinstance(images, list) or not images:
        return None
    first = images[0]
    if not isinstance(first, dict):
        return None
    raw_path = first.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    path = Path(raw_path)
    if path.is_absolute() or source_path is None:
        return path
    return source_path.parent / path


def _image_summary(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "png_parameters_readable": False,
    }
    if not path.exists():
        summary["error"] = "image file does not exist"
        return summary, None
    if not path.is_file():
        summary["error"] = "image path is not a file"
        return summary, None
    summary["bytes"] = path.stat().st_size
    summary["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
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


def _request_body_from_generation_result(data: dict[str, Any]) -> dict[str, Any] | None:
    request_body = data.get("request_body")
    return request_body if isinstance(request_body, dict) else None


def _png_info_parameters_from_generation_result(data: dict[str, Any]) -> dict[str, Any] | None:
    png_info = data.get("png_info")
    if not isinstance(png_info, dict):
        return None
    images = png_info.get("images")
    if not isinstance(images, list) or not images:
        return None
    first = images[0]
    return first if isinstance(first, dict) else None


def _diff_summary(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    *,
    approved_paths: set[str],
    missing_message: str,
) -> dict[str, Any]:
    if left is None or right is None:
        return {
            "match": False,
            "normalized_equal": False,
            "diff_count": None,
            "approved_diff_count": 0,
            "unapproved_diff_count": 1,
            "diffs": [],
            "unapproved_diffs": [{"path": "$", "reason": missing_message}],
            "error": missing_message,
        }
    diffs = [diff.as_dict() for diff in compare_render_parameters(left, right)]
    unapproved = [diff for diff in diffs if diff["path"] not in approved_paths]
    return {
        "match": not diffs,
        "normalized_equal": not diffs,
        "diff_count": len(diffs),
        "approved_diff_count": len(diffs) - len(unapproved),
        "unapproved_diff_count": len(unapproved),
        "diffs": diffs,
        "unapproved_diffs": unapproved,
        "left_normalized": normalize_render_parameters(left),
        "right_normalized": normalize_render_parameters(right),
    }


def _approved_paths(
    whitelist: list[dict[str, str]] | None,
    intentional_differences: list[dict[str, str]] | None,
) -> set[str]:
    entries = list(whitelist or []) + list(intentional_differences or [])
    return {str(entry.get("path") or "").strip() for entry in entries if entry.get("path")}


def _policy_evidence(
    bundle: dict[str, Any],
    *,
    expected_profile: str | None,
    required_rules: list[str],
) -> dict[str, Any]:
    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    extra = meta.get("extra") if isinstance(meta.get("extra"), dict) else {}
    policy = extra.get("policy") if isinstance(extra.get("policy"), dict) else {}
    trace = extra.get("policy_trace")
    trace = trace if isinstance(trace, list) else []
    enabled_rules = policy.get("enabled_rules")
    enabled_rules = enabled_rules if isinstance(enabled_rules, list) else []
    enabled_rule_ids = {_rule_id(value) for value in enabled_rules}
    required_rule_ids = {_rule_id(value) for value in required_rules}
    missing_rules = sorted(required_rule_ids - enabled_rule_ids)
    profile = policy.get("profile")
    profile_matches = True if expected_profile is None else profile == expected_profile
    return {
        "bundle_schema": bundle.get("schema"),
        "bundle_schema_valid": bundle.get("schema") == PROMPT_BUNDLE_SCHEMA,
        "enabled": bool(policy.get("enabled")),
        "profile": profile,
        "expected_profile": expected_profile,
        "profile_matches": profile_matches,
        "target": policy.get("target"),
        "enabled_rules": enabled_rules,
        "required_rules": sorted(required_rule_ids),
        "missing_required_rules": missing_rules,
        "required_rules_present": not missing_rules,
        "trace_count": len(trace),
        "trace_preview": trace[:10],
    }


def _rule_id(value: Any) -> str:
    return str(value).split("@", 1)[0].strip()


def _token_evidence(
    *,
    core_params: dict[str, Any] | None,
    expect_tokens: list[str],
    reject_tokens: list[str],
) -> dict[str, Any]:
    prompt = ""
    if core_params is not None:
        normalized = normalize_render_parameters(core_params)
        prompt = str(normalized.get("input") or "")
    missing_expected = [token for token in expect_tokens if token not in prompt]
    present_rejected = [token for token in reject_tokens if token in prompt]
    return {
        "prompt": prompt,
        "expect_tokens": expect_tokens,
        "reject_tokens": reject_tokens,
        "missing_expected_tokens": missing_expected,
        "present_rejected_tokens": present_rejected,
        "expected_tokens_present": not missing_expected,
        "rejected_tokens_absent": not present_rejected,
    }


def _check_messages(
    checks: dict[str, bool],
    policy: dict[str, Any],
    tokens: dict[str, Any],
) -> list[tuple[bool, str]]:
    return [
        (
            checks["generation_result_schema_valid"],
            f"GenerationResult schema must be {GENERATION_RESULT_SCHEMA}",
        ),
        (
            checks["prompt_bundle_schema_valid"],
            f"PromptBundle schema must be {PROMPT_BUNDLE_SCHEMA}",
        ),
        (checks["legacy_png_readable"], "legacy image PNG parameters are not readable"),
        (checks["core_png_readable"], "core image PNG parameters are not readable"),
        (checks["legacy_core_diff_approved"], "legacy/core parameter diff has unapproved entries"),
        (checks["core_request_matches_png"], "GenerationResult request_body differs from core PNG parameters"),
        (checks["generation_png_info_matches_png"], "GenerationResult png_info differs from core PNG parameters"),
        (checks["policy_enabled"], "PromptPolicyPipeline policy metadata is missing or disabled"),
        (checks["policy_trace_present"], "PromptPolicyPipeline policy_trace is missing or empty"),
        (
            checks["policy_profile_matches"],
            f"PromptPolicyPipeline profile mismatch: expected {policy.get('expected_profile')!r}, got {policy.get('profile')!r}",
        ),
        (
            checks["required_rules_present"],
            "PromptPolicyPipeline missing required rules: "
            + ", ".join(policy.get("missing_required_rules") or []),
        ),
        (
            checks["expected_tokens_present"],
            "core PNG prompt missing expected tokens: "
            + ", ".join(tokens.get("missing_expected_tokens") or []),
        ),
        (
            checks["rejected_tokens_absent"],
            "core PNG prompt still contains rejected tokens: "
            + ", ".join(tokens.get("present_rejected_tokens") or []),
        ),
        (checks["visual_pass"], "visual_result must be pass for PromptPolicyPipeline acceptance"),
    ]


def _normalize_visual_result(value: str) -> str:
    result = str(value or "pending").strip().lower()
    if result not in VISUAL_RESULTS:
        expected = ", ".join(VISUAL_RESULTS)
        raise ValueError(f"Unsupported visual result: {value!r}; expected one of {expected}")
    return result
