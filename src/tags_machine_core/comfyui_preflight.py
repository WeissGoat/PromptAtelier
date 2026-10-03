"""上云前检查：一个 ComfyUI workflow 需要哪些节点和模型文件，目标环境里有没有。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from tags_machine_core.clients.comfyui import (
    ComfyUIClient,
    PreparedComfyUIWorkflow,
    prepare_comfyui_workflow,
)
from tags_machine_core.config import ResolvedComfyUITarget
from tags_machine_core.contracts import PromptBundle, PromptText, RenderRequest
from tags_machine_core.execution import build_comfyui_transport
from tags_machine_core.nodes import NodeReader
from tags_machine_core.renderers import ComfyUIRenderAdapter
from tags_machine_core.renderers.comfyui_workflow import (
    WorkflowPathStyle,
    is_workflow_link,
    iter_workflow_file_refs,
    workflow_class_types,
)


PREFLIGHT_SCHEMA = "tags-machine-core.comfyui-preflight/v1"
INPUT_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def preflight_render_request(
    *,
    artist_node: str | Path | None = None,
    workflow: str | Path | None = None,
    output_nodes: list[str] | None = None,
) -> RenderRequest:
    """按真实渲染流程（artist node 绑定、node_overrides）生成待检查的请求。"""
    if artist_node:
        node = NodeReader().read(artist_node)
        bundle = PromptBundle(prompt=PromptText(positive="preflight", negative="preflight"))
        return ComfyUIRenderAdapter().build_request(bundle, seed=0, artist=node)
    if not workflow:
        raise ValueError("ComfyUI preflight needs an artist node or an API workflow")
    return RenderRequest(
        backend="comfyui",
        prompt="preflight",
        params={
            "workflow_json": json.loads(Path(workflow).read_text(encoding="utf-8")),
            "output_nodes": list(output_nodes or []),
        },
    )


def run_comfyui_preflight(
    request: RenderRequest,
    *,
    target: ResolvedComfyUITarget | None = None,
    manifest_path: str | Path | None = None,
    live: bool = False,
    prune: bool = True,
    path_style: WorkflowPathStyle = "posix",
) -> dict[str, Any]:
    """没给 target 时按 path_style 准备；live=True 会请求目标的 /object_info。"""
    prepared = prepare_comfyui_workflow(
        request,
        prune_to_output_nodes=prune and (target.prune_to_output_nodes if target else True),
        path_style=target.path_style if target else path_style,
    )
    object_info = None
    if live:
        if target is None:
            raise ValueError("ComfyUI live preflight needs a configured target")
        transport = build_comfyui_transport(target)
        if not isinstance(transport, ComfyUIClient):
            raise ValueError(f"ComfyUI live preflight needs a native target, got {target.transport}")
        object_info = transport.object_info()
    report = comfyui_preflight_report(
        prepared,
        manifest=load_runtime_manifest(manifest_path) if manifest_path else None,
        object_info=object_info,
    )
    if target is not None:
        report["target_name"] = target.name
    return report


def load_runtime_manifest(path: str | Path) -> dict[str, Any]:
    """读取运行环境清单；models_file 指向的模型清单合并进 models。"""
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"ComfyUI runtime manifest must be a mapping: {path}")
    models_file = data.get("models_file")
    if models_file:
        models = yaml.safe_load((path.parent / models_file).read_text(encoding="utf-8")) or {}
        data["models"] = [*(data.get("models") or []), *(models.get("models") or [])]
    return data


def comfyui_preflight_report(
    prepared: PreparedComfyUIWorkflow,
    *,
    manifest: dict[str, Any] | None = None,
    object_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = prepared.prompt
    class_types = sorted(workflow_class_types(prompt))
    uploaded = {
        f"{item.subfolder}/{item.name}" if item.subfolder else item.name
        for item in prepared.input_files
    }
    model_refs: list[dict[str, Any]] = []
    input_images: list[dict[str, Any]] = []
    for node_id, input_name, value in iter_workflow_file_refs(prompt):
        ref = {
            "node": node_id,
            "class_type": prompt[node_id].get("class_type"),
            "input": input_name,
            "value": value,
        }
        if value.lower().endswith(INPUT_IMAGE_SUFFIXES):
            input_images.append({**ref, "uploaded": value in uploaded})
        else:
            model_refs.append(ref)

    report: dict[str, Any] = {
        "schema": PREFLIGHT_SCHEMA,
        "workflow": prepared.summary(),
        "class_types": class_types,
        "model_refs": model_refs,
        "input_images": input_images,
    }
    problems: list[str] = []
    if manifest is not None:
        report["manifest"] = _check_manifest(manifest, class_types, model_refs)
        problems.extend(
            f"manifest: missing model {item['value']} (node {item['node']})"
            for item in report["manifest"]["missing_models"]
        )
    if object_info is not None:
        report["target"] = _check_object_info(object_info, prompt, uploaded=uploaded)
        problems.extend(report["target"]["problems"])
    report["problems"] = problems
    report["ok"] = not problems
    return report


def _check_manifest(
    manifest: dict[str, Any],
    class_types: list[str],
    model_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    provided: dict[str, str] = {}
    for node in manifest.get("custom_nodes") or []:
        for class_type in node.get("provides") or []:
            provided[str(class_type)] = str(node.get("name"))
    model_paths = [
        str(item.get("path") or "").replace("\\", "/") for item in manifest.get("models") or []
    ]

    found: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for ref in model_refs:
        normalized = ref["value"].replace("\\", "/")
        match = next(
            (path for path in model_paths if path == normalized or path.endswith("/" + normalized)),
            None,
        )
        if match:
            found.append({**ref, "manifest_path": match})
        else:
            missing.append(ref)
    return {
        "custom_nodes": {item: provided[item] for item in class_types if item in provided},
        # 不在 manifest 里的要么是 ComfyUI 内置节点，要么是漏装的插件；用 --live 对目标确认。
        "not_provided_by_manifest": [item for item in class_types if item not in provided],
        "models": found,
        "missing_models": missing,
    }


def _check_object_info(
    object_info: dict[str, Any],
    prompt: dict[str, Any],
    *,
    uploaded: set[str],
) -> dict[str, Any]:
    """按 ComfyUI 自己的校验规则检查：节点类是否存在、下拉值是否在目标列表里。"""
    missing_classes = sorted(
        {
            str(node.get("class_type"))
            for node in prompt.values()
            if node.get("class_type") not in object_info
        }
    )
    missing_values: list[dict[str, Any]] = []
    for node_id, node in prompt.items():
        info = object_info.get(node.get("class_type"))
        if not isinstance(info, dict):
            continue
        declared: dict[str, Any] = {}
        for section in ("required", "optional"):
            declared.update((info.get("input") or {}).get(section) or {})
        for input_name, value in (node.get("inputs") or {}).items():
            if not isinstance(value, str) or is_workflow_link(value) or value in uploaded:
                continue
            options = _combo_options(declared.get(input_name))
            if options is not None and value not in options:
                missing_values.append(
                    {
                        "node": node_id,
                        "class_type": node.get("class_type"),
                        "input": input_name,
                        "value": value,
                    }
                )
    problems = [f"target: node class {item} is not installed" for item in missing_classes]
    problems.extend(
        f"target: {item['class_type']} #{item['node']} {item['input']}={item['value']!r} "
        "is not available"
        for item in missing_values
    )
    return {
        "missing_class_types": missing_classes,
        "missing_values": missing_values,
        "problems": problems,
    }


def _combo_options(spec: Any) -> set[Any] | None:
    if not isinstance(spec, (list, tuple)) or not spec:
        return None
    first = spec[0]
    if isinstance(first, list):
        return set(first)
    # ComfyUI v3 节点的下拉写成 ["COMBO", {"options": [...]}]。
    if first == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        options = spec[1].get("options")
        if isinstance(options, list):
            return set(options)
    return None
