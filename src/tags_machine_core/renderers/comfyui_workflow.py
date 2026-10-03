from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterator, Literal


REQUIRED_INPUT_KEYS = (
    "positive_prompt",
    "negative_prompt",
    "width",
    "height",
    "seed",
)

WorkflowPathStyle = Literal["native", "posix"]

# 只把"看起来像相对文件路径"的字符串当成模型/输入文件引用，避免误改提示词里的反斜杠。
WORKFLOW_FILE_SUFFIXES = (
    ".safetensors",
    ".sft",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".gguf",
    ".onnx",
    ".pkl",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
)
_ABSOLUTE_PATH_PATTERN = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")


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


def apply_node_overrides(workflow: dict[str, Any], overrides: dict[str, Any]) -> None:
    for path, value in overrides.items():
        set_workflow_value(workflow, str(path), value)


def set_workflow_value(workflow: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in path.split(".") if part]
    if not parts:
        raise ValueError("node_overrides path cannot be empty")
    current: Any = workflow
    for part in parts[:-1]:
        if not isinstance(current, dict):
            raise ValueError(f"Cannot apply node override through non-mapping path: {path}")
        current = current.setdefault(part, {})
    if not isinstance(current, dict):
        raise ValueError(f"Cannot apply node override to non-mapping path: {path}")
    current[parts[-1]] = value


def is_workflow_link(value: Any) -> bool:
    """API workflow 里的连线写成 ["源节点 id", 输出序号]。"""
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
    )


def workflow_ancestors(workflow: dict[str, Any], node_ids: list[str] | tuple[str, ...]) -> set[str]:
    missing = [node_id for node_id in node_ids if node_id not in workflow]
    if missing:
        raise ValueError(
            "ComfyUI output_nodes not found in workflow: " + ", ".join(missing)
        )
    seen: set[str] = set()
    stack = list(node_ids)
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = workflow.get(node_id)
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            continue
        for value in inputs.values():
            # 指向不存在节点的悬空连线保持原样，交给 ComfyUI 报错。
            if is_workflow_link(value) and value[0] in workflow:
                stack.append(value[0])
    return seen


def prune_workflow_to_outputs(
    workflow: dict[str, Any],
    output_nodes: list[str] | tuple[str, ...],
) -> tuple[dict[str, Any], list[str]]:
    """只保留 output_nodes 及其上游节点。

    ComfyUI 会执行 prompt 里所有输出节点，并要求每个 class_type 都已安装；
    裁剪后其它预览/保存分支不会执行，也不需要安装它们用到的插件。
    """
    keep = workflow_ancestors(workflow, output_nodes)
    pruned = {node_id: node for node_id, node in workflow.items() if node_id in keep}
    removed = [node_id for node_id in workflow if node_id not in keep]
    return pruned, removed


def normalize_workflow_file_paths(
    workflow: dict[str, Any],
    path_style: WorkflowPathStyle,
) -> list[str]:
    """原地把相对文件路径里的 Windows 分隔符改成目标平台的写法。

    ComfyUI 校验下拉值时做精确匹配；Windows 上导出的 LoRA 名
    (例如 "风格\\x.safetensors") 在 Linux 上会报 value_not_in_list。
    只支持 posix：Linux 列表里的路径一律用 "/"，反过来转换会弄坏
    Impact Subpack 这类在 Windows 上也用 "bbox/x.pt" 的节点。
    """
    if path_style == "native":
        return []
    if path_style != "posix":
        raise ValueError(f"Unsupported ComfyUI path_style: {path_style!r}")
    changed: list[str] = []
    for node_id, input_name, value in iter_workflow_file_refs(workflow):
        if "\\" not in value:
            continue
        workflow[node_id]["inputs"][input_name] = value.replace("\\", "/")
        changed.append(f"{node_id}.inputs.{input_name}")
    return changed


def iter_workflow_file_refs(workflow: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    for node_id, node in workflow.items():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict):
            continue
        for input_name, value in inputs.items():
            if isinstance(value, str) and looks_like_relative_file_path(value):
                yield str(node_id), str(input_name), value


def looks_like_relative_file_path(value: str) -> bool:
    if not value or len(value) > 512 or "\n" in value or "\r" in value:
        return False
    if _ABSOLUTE_PATH_PATTERN.match(value):
        return False
    return value.lower().endswith(WORKFLOW_FILE_SUFFIXES)
