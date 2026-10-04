"""Custom 工作区的出图任务：单次 /generate 和后台批量 /generate/batch 共用同一条出图路径。"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from tags_machine_core.web.services.job_manager import JobContext


GENERATE_BATCH_JOB = "generate-batch"
GENERATE_BATCH_SCHEMA = "tags-machine-core.web.generate-batch/v1"
MAX_BATCH_ITEMS = 2000
# 原样带回给前端展示的项目字段（标签、分组、seed 等），后端不解释。
_ITEM_DISPLAY_KEYS = ("label", "group", "seed", "labels")
_GENERATE_OPTION_KEYS = ("output_dir", "comfyui_target", "random_selections")

Emit = Callable[[str, dict[str, Any]], None]


def run_generate(api: Any, prepared: dict[str, Any], emit: Emit) -> dict[str, Any]:
    emit("generation_started", {})
    # on_progress 只在进程内传给执行器（ComfyUI 的启动/排队/下载进度），不会序列化进结果。
    result = api.generate({**prepared, "on_progress": emit})
    if prepared.get("random_selections"):
        result["random_selections"] = prepared["random_selections"]
    emit("generation_finished", {"image_count": len(result.get("images") or [])})
    return result


def attach_random_selections(payload: dict[str, Any]) -> dict[str, Any]:
    selections = payload.get("random_selections")
    if selections is None:
        return payload
    _check_random_selections(selections)
    request_data = payload.get("render_request") or payload.get("request")
    if not isinstance(request_data, dict):
        raise ValueError("random selections require render_request")
    render_request = dict(request_data)
    meta = dict(render_request.get("meta") or {})
    meta["random_nodes"] = selections
    render_request["meta"] = meta
    result = dict(payload)
    result["render_request"] = render_request
    result["random_selections"] = selections
    return result


def validate_generate_batch(payload: dict[str, Any]) -> dict[str, Any]:
    """提交时只查结构；提示词拼接和出图都在任务里逐项做，一项失败不影响其他项。"""
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("generate batch requires a non-empty items list")
    if len(items) > MAX_BATCH_ITEMS:
        raise ValueError(f"generate batch accepts at most {MAX_BATCH_ITEMS} items")
    checked: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{index}] must be an object")
        if not isinstance(item.get("compose_request"), dict):
            raise ValueError(f"items[{index}].compose_request must be an object")
        generate = item.get("generate") or {}
        if not isinstance(generate, dict):
            raise ValueError(f"items[{index}].generate must be an object")
        if generate.get("random_selections") is not None:
            _check_random_selections(generate["random_selections"])
        checked.append(
            {
                "compose_request": item["compose_request"],
                "generate": {key: generate[key] for key in _GENERATE_OPTION_KEYS if generate.get(key) is not None},
                "display": {key: item[key] for key in _ITEM_DISPLAY_KEYS if item.get(key) is not None},
            }
        )
    return {
        "label": str(payload.get("label") or "后台出图"),
        "kind": str(payload.get("kind") or "custom"),
        "output_dir": payload.get("output_dir"),
        "items": checked,
    }


def run_generate_batch(api: Any, batch: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    items = [
        {"index": index, **entry["display"], "status": "queued", "images": [], "error": None}
        for index, entry in enumerate(batch["items"])
    ]

    def snapshot() -> dict[str, Any]:
        counts = {status: 0 for status in ("queued", "running", "succeeded", "failed", "cancelled")}
        for item in items:
            counts[item["status"]] += 1
        return {
            "schema": GENERATE_BATCH_SCHEMA,
            "label": batch["label"],
            "kind": batch["kind"],
            "output_dir": batch["output_dir"],
            "total": len(items),
            "counts": counts,
            # 浅拷贝每一项：轮询序列化时不会碰到正在修改的字典。
            "items": [dict(item) for item in items],
        }

    ctx.set_result(snapshot())
    for index, entry in enumerate(batch["items"]):
        item = items[index]
        if ctx.cancel_requested:
            for rest in items[index:]:
                rest["status"] = "cancelled"
            break
        item.update(status="running", started_at=time.time())
        ctx.set_result(snapshot())
        ctx.emit("batch_item_started", {"item_index": index})

        def emit(event_type: str, payload: dict[str, Any], index: int = index) -> None:
            ctx.emit(event_type, {**payload, "item_index": index})

        try:
            plan = api.resolve_compose_render_plan(entry["compose_request"])
            if plan.get("status") != "ready" or not plan.get("render_request"):
                raise ValueError("该组合需要外部 Agent 先完成提示词拼接。")
            prepared = attach_random_selections({"render_request": plan["render_request"], **entry["generate"]})
            result = run_generate(api, prepared, emit)
            item.update(status="succeeded", images=result.get("images") or [])
        except Exception as exc:  # noqa: BLE001  单项失败记在该项上，继续下一项
            item.update(status="failed", error=str(exc) or type(exc).__name__)
        item["finished_at"] = time.time()
        ctx.emit("batch_item_finished", {"item_index": index, "status": item["status"]})
        ctx.set_result(snapshot())

    final = snapshot()
    if final["counts"]["failed"] and not final["counts"]["succeeded"] and not final["counts"]["cancelled"]:
        first_error = next(item["error"] for item in items if item["status"] == "failed")
        raise RuntimeError(f"全部 {len(items)} 项都失败了：{first_error}")
    return final


def _check_random_selections(selections: Any) -> None:
    if not isinstance(selections, list) or not all(isinstance(item, dict) for item in selections):
        raise ValueError("random_selections must be a list of objects")
