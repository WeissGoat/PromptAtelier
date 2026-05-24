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

EXPECTED_FILE_BY_KIND = {
    "character": "meta.yaml",
    "action": "meta.yaml",
    "background": "meta.yaml",
    "style": "node.yaml",
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
