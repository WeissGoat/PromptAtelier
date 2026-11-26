"""Custom 工作区的出图任务：单次 /generate 和后台批量 /generate/batch 共用同一条出图路径。"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

from tags_machine_core.error_classification import fatal_generation_error_reason
from tags_machine_core.web.services.job_manager import JobContext, JobRecord

GENERATE_BATCH_JOB = "generate-batch"
GENERATE_BATCH_SCHEMA = "tags-machine-core.web.generate-batch/v1"
MAX_BATCH_ITEMS = 2000
MAX_CONSECUTIVE_FAILURES = 5
# 原样带回给前端展示的项目字段（标签、分组、seed 等），后端不解释。
_ITEM_DISPLAY_KEYS = ("label", "group", "seed", "labels")
_GENERATE_OPTION_KEYS = ("output_dir", "comfyui_target", "random_selections", "skip_duplicates")

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
        if "skip_duplicates" in generate and not isinstance(generate["skip_duplicates"], bool):
            raise ValueError(f"items[{index}].generate.skip_duplicates must be a boolean")
        checked.append(
            {
                "compose_request": item["compose_request"],
                "generate": {key: generate[key] for key in _GENERATE_OPTION_KEYS if generate.get(key) is not None},
                "display": {key: item[key] for key in _ITEM_DISPLAY_KEYS if item.get(key) is not None},
            }
        )
    frame_interval = _non_negative_float(payload.get("frame_interval"), "frame_interval")
    frame_interval_jitter = _non_negative_float(payload.get("frame_interval_jitter"), "frame_interval_jitter")
    return {
        "label": str(payload.get("label") or "后台出图"),
        "kind": str(payload.get("kind") or "custom"),
        "output_dir": payload.get("output_dir"),
        "frame_interval": frame_interval,
        "frame_interval_jitter": frame_interval_jitter,
        "items": checked,
    }


def _non_negative_float(value: Any, name: str) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative number") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be >= 0")
    return parsed


def _batch_snapshot(
    batch: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    aborted_reason: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": GENERATE_BATCH_SCHEMA,
        "label": batch["label"],
        "kind": batch["kind"],
        "output_dir": batch["output_dir"],
        "total": len(items),
        "counts": _count_items(items),
        # 浅拷贝每一项：轮询序列化时不会碰到正在修改的字典。
        "items": [dict(item) for item in items],
    }
    if aborted_reason is not None:
        data["aborted_reason"] = aborted_reason
    return data


def _count_items(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in ("queued", "running", "succeeded", "failed", "cancelled")}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return counts


def recover_interrupted_batch(job: JobRecord) -> None:
    """后端重启时还在跑的批量任务：正在跑的那一项退回排队，供"继续剩余项"重跑。"""
    result = job.result
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        return
    for item in result["items"]:
        if item.get("status") == "running":
            item["status"] = "queued"
    result["counts"] = _count_items(result["items"])


def run_generate_batch(
    api: Any,
    batch: dict[str, Any],
    ctx: JobContext,
    previous: dict[str, Any] | None = None,
    reuse: Any = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    jitter_fn: Callable[[float, float], float] = random.uniform,
) -> dict[str, Any]:
    """逐项出图。previous 是同一任务上次的结果：已成功的项原样保留，其余的重跑。"""
    done = {
        item.get("index"): item
        for item in (previous or {}).get("items") or []
        if isinstance(item, dict) and item.get("status") == "succeeded"
    }
    items = [
        dict(done[index]) if index in done
        else {"index": index, **entry["display"], "status": "queued", "images": [], "error": None}
        for index, entry in enumerate(batch["items"])
    ]

    aborted_reason: str | None = None
    consecutive_failures = 0

    def snapshot() -> dict[str, Any]:
        return _batch_snapshot(batch, items, aborted_reason=aborted_reason)

    ctx.set_result(snapshot())
    for index, entry in enumerate(batch["items"]):
        item = items[index]
        if item["status"] == "succeeded":
            continue
        if ctx.cancel_requested:
            for rest in items[index:]:
                if rest["status"] != "succeeded":
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
            trace = (entry["compose_request"].get("compose") or {}).get("contract")
            skip = entry["generate"].get("skip_duplicates", bool(trace))
            def generate(prepared=prepared, emit=emit):
                return run_generate(api, prepared, emit)

            result = reuse.run(api, entry["compose_request"], prepared, generate, force=not skip) if reuse and (trace or skip) else generate()
            item.update(status="succeeded", images=result.get("images") or [], error=None, cache_hit=bool(result.get("cache_hit")))
            consecutive_failures = 0
            if item["cache_hit"]:
                emit("generation_reused", {"image_count": len(item["images"])})
        except Exception as exc:  # noqa: BLE001  单项失败记在该项上；致命错误或连续失败则触发熔断
            item.update(status="failed", error=str(exc) or type(exc).__name__)
            consecutive_failures += 1
            fatal_reason = fatal_generation_error_reason(exc)
            if fatal_reason:
                aborted_reason = f"触发熔断（致命错误）：{fatal_reason}"
            elif consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                aborted_reason = f"触发熔断：连续 {consecutive_failures} 项失败（最近错误：{item['error']}）"
        item["finished_at"] = time.time()
        ctx.emit("batch_item_finished", {"item_index": index, "status": item["status"]})
        if aborted_reason is not None:
            for rest in items[index + 1 :]:
                if rest["status"] != "succeeded":
                    rest["status"] = "cancelled"
            ctx.emit("batch_aborted", {"item_index": index, "reason": aborted_reason})
            ctx.set_result(snapshot())
            break
        ctx.set_result(snapshot())

        base_interval = float(batch.get("frame_interval") or 0.0)
        jitter = float(batch.get("frame_interval_jitter") or 0.0)
        has_remaining = any(rest["status"] != "succeeded" for rest in items[index + 1 :])
        if (
            (base_interval > 0.0 or jitter > 0.0)
            and not item.get("cache_hit")
            and has_remaining
            and not ctx.cancel_requested
        ):
            wait = base_interval + (jitter_fn(0.0, jitter) if jitter > 0.0 else 0.0)
            if wait > 0.0:
                ctx.emit("batch_pacing_wait", {"item_index": index, "wait_seconds": round(wait, 3)})
                _sleep_with_cancel(wait, ctx, sleep)

    final = snapshot()
    if aborted_reason is not None and not final["counts"]["succeeded"]:
        raise RuntimeError(aborted_reason)
    if final["counts"]["failed"] and not final["counts"]["succeeded"] and not final["counts"]["cancelled"]:
        first_error = next(item["error"] for item in items if item["status"] == "failed")
        raise RuntimeError(f"全部 {len(items)} 项都失败了：{first_error}")
    return final


def _sleep_with_cancel(wait: float, ctx: JobContext, sleep: Callable[[float], None]) -> None:
    if sleep is not time.sleep or wait <= 0.25:
        sleep(wait)
        return
    remaining = wait
    while remaining > 0.0 and not ctx.cancel_requested:
        step = min(0.25, remaining)
        sleep(step)
        remaining -= step


def _check_random_selections(selections: Any) -> None:
    if not isinstance(selections, list) or not all(isinstance(item, dict) for item in selections):
        raise ValueError("random_selections must be a list of objects")
