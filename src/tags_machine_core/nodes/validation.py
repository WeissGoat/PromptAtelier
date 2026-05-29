from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .reader import NodeReader


FORBIDDEN_KEYS_BY_KIND = {
    "character": {
        "rules",
        "profiles",
        "include_scopes",
        "exclude_scopes",
        "shot",
        "constraints",
    },
    "action": {
        "rules",
        "profiles",
        "include_scopes",
        "exclude_scopes",
        "shot",
        "constraints",
        "pose",
        "camera",
        "focus",
        "visible_parts",
        "character_sections",
        "include_character_sections",
        "suppress_character_sections",
        "renderers",
        "generation",
        "backend",
        "params",
        "style",
        "artist",
        "quality",
        "prompt",
    },
    "background": {
        "rules",
        "profiles",
        "include_scopes",
        "exclude_scopes",
        "shot",
        "constraints",
        "renderers",
    },
    "style": {
        "rules",
        "profiles",
        "include_scopes",
        "exclude_scopes",
        "shot",
        "constraints",
    },
}

SUPPORTED_V1_KINDS = {"character", "action", "background", "style"}

EXPECTED_SCHEMA_BY_KIND = {
    "character": "tags-machine.character/v1",
    "action": "tags-machine.action/v1",
    "background": "tags-machine.background/v1",
    "style": "tags-machine.style/v1",
}

EXPECTED_FILE_BY_KIND = {
    "character": "meta.yaml",
    "action": "meta.yaml",
    "background": "meta.yaml",
    "style": "node.yaml",
}

REQUIRED_TAG_SECTIONS_BY_KIND = {
    "character": ("character",),
    "action": ("action",),
    "background": ("background",),
    "style": ("style",),
}


def validate_node_tree(source: str | Path) -> dict[str, Any]:
    """只读扫描结构化节点目录，验证 v1 节点的文件名和关键字段。"""
    source_path = Path(source)
    yaml_paths = _collect_node_yaml_paths(source_path)
    items = [_validate_node_yaml(path, source_path) for path in yaml_paths]
    issue_counts: dict[str, int] = {}
    for item in items:
        for issue in item.get("issues", []):
            code = str(issue.get("code") or "unknown")
            issue_counts[code] = issue_counts.get(code, 0) + 1

    global_issues: list[dict[str, Any]] = []
    if not yaml_paths:
        global_issues.append(
            {
                "code": "node_yaml_not_found",
                "severity": "error",
                "message": "没有找到 node.yaml 或 meta.yaml。",
            }
        )
        issue_counts["node_yaml_not_found"] = issue_counts.get("node_yaml_not_found", 0) + 1

    failed_count = sum(1 for item in items if item["status"] == "fail") + len(global_issues)
    return {
        "schema": "tags-machine-core.node-tree-validation/v1",
        "source": str(source_path),
        "valid": failed_count == 0,
        "result": "pass" if failed_count == 0 else "fail",
        "summary": {
            "total_files": len(items),
            "pass_count": sum(1 for item in items if item["status"] == "pass"),
            "fail_count": failed_count,
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "issues": global_issues,
        "items": items,
    }


def _collect_node_yaml_paths(source: Path) -> list[Path]:
    if source.is_file():
        if source.name in {"node.yaml", "meta.yaml"}:
            return [source]
        return []
    if not source.exists():
        raise FileNotFoundError(f"Node tree not found: {source}")
    return sorted(
        path
        for path in source.rglob("*.yaml")
        if path.name in {"node.yaml", "meta.yaml"} and path.is_file()
    )


def _validate_node_yaml(path: Path, source_root: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    relative_path = _relative_text(path, source_root)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return _failed_item(
            path,
            relative_path,
            [
                {
                    "code": "yaml_parse_error",
                    "severity": "error",
                    "message": str(exc),
                }
            ],
        )

    if not isinstance(data, dict):
        return _failed_item(
            path,
            relative_path,
            [
                {
                    "code": "invalid_yaml_mapping",
                    "severity": "error",
                    "message": "节点 YAML 必须是 mapping。",
                }
            ],
        )

    raw_kind = str(data.get("kind") or "").strip()
    raw_node_id = str(data.get("id") or path.parent.name).strip() or path.parent.name
    if not raw_kind:
        _append_issue(issues, "missing_node_kind", "节点缺少 kind。")
    elif raw_kind not in SUPPORTED_V1_KINDS:
        _append_issue(
            issues,
            "unsupported_v1_kind",
            f"v1 结构化节点暂不支持 kind={raw_kind}。",
            details={"supported": sorted(SUPPORTED_V1_KINDS), "actual": raw_kind},
        )
    if issues:
        return {
            "path": str(path),
            "relative_path": relative_path,
            "status": "fail",
            "kind": raw_kind or None,
            "node_id": raw_node_id,
            "issues": issues,
        }

    try:
        node = NodeReader().read(path)
    except Exception as exc:
        return _failed_item(
            path,
            relative_path,
            [
                {
                    "code": "node_read_error",
                    "severity": "error",
                    "message": str(exc),
                }
            ],
        )

    kind = node.kind or raw_kind
    expected_schema = EXPECTED_SCHEMA_BY_KIND.get(kind)
    actual_schema = data.get("schema")
    if expected_schema and actual_schema != expected_schema:
        _append_issue(
            issues,
            "node_schema_mismatch",
            f"{kind} 节点 schema 应为 {expected_schema}。",
            details={"expected": expected_schema, "actual": actual_schema},
        )

    expected_file = EXPECTED_FILE_BY_KIND.get(kind)
    if expected_file and path.name != expected_file:
        _append_issue(
            issues,
            "node_file_name_mismatch",
            f"{kind} 节点应使用 {expected_file}。",
            details={"expected": expected_file, "actual": path.name},
        )

    for key_path in _forbidden_yaml_key_paths(data, FORBIDDEN_KEYS_BY_KIND.get(kind, set())):
        _append_issue(
            issues,
            "forbidden_v1_field",
            "节点包含 v1 不允许的规则或结构字段。",
            details={"field": key_path},
        )

    _validate_required_tag_sections(issues, data, kind)

    if kind == "action" and not str(data.get("character_scope") or "").strip():
        _append_issue(issues, "action_missing_character_scope", "action 节点缺少 character_scope。")
    if kind == "style":
        renderers = data.get("renderers")
        if not isinstance(renderers, dict) or not isinstance(renderers.get("novelai"), dict):
            _append_issue(
                issues,
                "style_missing_renderers_novelai",
                "style 节点缺少 renderers.novelai。",
            )

    return {
        "path": str(path),
        "relative_path": relative_path,
        "status": "fail" if issues else "pass",
        "kind": kind,
        "node_id": node.id,
        "issues": issues,
    }


def _failed_item(path: Path, relative_path: str, issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "path": str(path),
        "relative_path": relative_path,
        "status": "fail",
        "kind": None,
        "node_id": None,
        "issues": issues,
    }


def _append_issue(
    issues: list[dict[str, Any]],
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    issue: dict[str, Any] = {
        "code": code,
        "severity": "error",
        "message": message,
    }
    if details:
        issue["details"] = details
    issues.append(issue)


def _validate_required_tag_sections(
    issues: list[dict[str, Any]],
    data: dict[str, Any],
    kind: str,
) -> None:
    required_sections = REQUIRED_TAG_SECTIONS_BY_KIND.get(kind, ())
    if not required_sections:
        return
    tags = data.get("tags")
    if not isinstance(tags, dict):
        _append_issue(
            issues,
            "invalid_tags_mapping",
            "节点 tags 必须是按 section 分组的 mapping。",
        )
        return
    missing = [
        section
        for section in required_sections
        if not _has_non_empty_tag_values(tags.get(section))
    ]
    if missing:
        _append_issue(
            issues,
            "missing_required_tag_section",
            "节点缺少 v1 必需的 tags section。",
            details={
                "missing": missing,
                "available": sorted(str(key) for key in tags.keys()),
            },
        )


def _has_non_empty_tag_values(value: Any) -> bool:
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    if isinstance(value, str):
        return bool(value.strip())
    return False


def _forbidden_yaml_key_paths(value: Any, forbidden_keys: set[str], prefix: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            key_path = f"{prefix}.{key_text}"
            if key_text in forbidden_keys:
                paths.append(key_path)
            paths.extend(_forbidden_yaml_key_paths(item, forbidden_keys, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_forbidden_yaml_key_paths(item, forbidden_keys, f"{prefix}[{index}]"))
    return paths


def _relative_text(path: Path, source_root: Path) -> str:
    try:
        return str(path.relative_to(source_root))
    except ValueError:
        return str(path)
