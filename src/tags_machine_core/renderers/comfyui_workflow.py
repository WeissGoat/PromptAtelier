from __future__ import annotations

import hashlib
import json
from typing import Any


REQUIRED_INPUT_KEYS = (
    "positive_prompt",
    "negative_prompt",
    "width",
    "height",
    "seed",
)


def workflow_hash(workflow: dict[str, Any]) -> str:
    text = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_api_workflow(workflow: dict[str, Any], *, source: str) -> None:
    if not isinstance(workflow, dict):
        raise ValueError(f"ComfyUI workflow must be a mapping: {source}")
    if isinstance(workflow.get("nodes"), list) and isinstance(workflow.get("links"), list):
        raise ValueError(
            "ComfyUI workflow must be a ComfyUI API workflow exported with "
            f"File -> Export (API), got UI workflow: {source}"
        )
    if not workflow:
        raise ValueError(f"ComfyUI API workflow cannot be empty: {source}")

    invalid_nodes: list[str] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str):
            invalid_nodes.append(str(node_id))
            continue
        inputs = node.get("inputs")
        if inputs is not None and not isinstance(inputs, dict):
            invalid_nodes.append(str(node_id))
    if invalid_nodes:
        shown = ", ".join(invalid_nodes[:10])
        raise ValueError(
            "ComfyUI API workflow nodes must contain class_type and mapping inputs; "
            f"invalid nodes in {source}: {shown}"
        )


def required_input_paths(payload: dict[str, Any]) -> dict[str, Any]:
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("ComfyUI artist node requires renderers.comfyui.inputs")
    missing = [key for key in REQUIRED_INPUT_KEYS if key not in inputs]
    if missing:
        raise ValueError(
            "ComfyUI artist node missing required input bindings: " + ", ".join(missing)
        )
    return inputs


def optional_input_paths(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("optional_inputs") or {}
    if not isinstance(value, dict):
        raise ValueError("ComfyUI renderers.comfyui.optional_inputs must be a mapping")
    return value


def output_node_ids(payload: dict[str, Any]) -> list[str]:
    value = payload.get("output_nodes") or []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError("ComfyUI renderers.comfyui.output_nodes must be a string or list")


def build_bound_overrides(
    *,
    inputs: dict[str, Any],
    values: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for key, value in values.items():
        if key not in inputs:
            continue
        for path in normalize_binding_paths(inputs[key], source=f"{source}.{key}"):
            overrides[path] = value
    return overrides


def normalize_binding_paths(value: Any, *, source: str) -> list[str]:
    if isinstance(value, str):
        path = value.strip()
        if not path:
            raise ValueError(f"ComfyUI binding path cannot be empty: {source}")
        return [path]
    if isinstance(value, list):
        paths: list[str] = []
        for index, item in enumerate(value):
            paths.extend(normalize_binding_paths(item, source=f"{source}[{index}]"))
        return paths
    raise ValueError(f"ComfyUI binding path must be string or list of strings: {source}")


def workflow_class_types(workflow: dict[str, Any]) -> set[str]:
    class_types: set[str] = set()
    for node in workflow.values():
        if isinstance(node, dict) and isinstance(node.get("class_type"), str):
            class_types.add(node["class_type"])
    return class_types
