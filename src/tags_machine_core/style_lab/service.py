from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any

from tags_machine_core.logging_config import get_logger

from tags_machine_core.llm import split_prompt_tags, translate_tags

from .compare import compare_with_source
from .regenerate import RegenSettings, build_regen_request, expected_diff_keys, plan_seeds
from .workspace import RUN_SCHEMA, WorkspaceInfo, WorkspaceStore


logger = get_logger(__name__)

REGENERATE_JOB = "style_lab_regenerate"
PRETRANSLATE_JOB = "style_lab_pretranslate"
_PRETRANSLATE_CHUNK = 160
_ACTIVE_JOB_STATUSES = {"queued", "running", "cancelling"}


class StyleLabService:
    def __init__(self, *, store: WorkspaceStore, job_manager: Any, generation_api: Any, llm_client: Any = None):
        self.store = store
        self.job_manager = job_manager
        self.generation_api = generation_api
        self.llm_client = llm_client
        self._pretranslate_jobs: dict[str, str] = {}
        # 每个任务各跑一个线程；同一账号并发请求 NovelAI 会 429，所以 Style Lab 的出图串行执行。
        self._generate_lock = threading.Lock()

    def start_regenerate(self, info: WorkspaceInfo, image_id: str, settings: RegenSettings) -> dict[str, Any]:
        """原参重生：逐张串行出图，每张出完立刻和源图对照并写回 run.json。"""
        record = self.store.find_image(info, image_id)
        if not record.has_metadata:
            raise ValueError(f"Image has no NovelAI metadata: {record.rel_path}")
        seeds = plan_seeds(settings, record.seed)
        requests = [build_regen_request(record, settings, seed) for seed in seeds]
        expected = sorted(expected_diff_keys(settings, record))
        run_id, run_dir = self.store.new_run_dir(info)
        run: dict[str, Any] = {
            "schema": RUN_SCHEMA,
            "id": run_id,
            "kind": "regenerate",
            "status": "queued",
            "created_at": time.time(),
            "finished_at": None,
            "job_id": None,
            "source": {"image_id": record.id, "path": record.path, "rel_path": record.rel_path},
            "settings": settings.model_dump(mode="json"),
            "expected_diff_keys": expected,
            "warnings": _source_warnings(record.flags),
            "items": [{"index": index, "seed": seed, "status": "queued"} for index, seed in enumerate(seeds)],
        }

        def worker(ctx):
            # 任务线程只用自己从磁盘读出的副本；提交方持有 store 锁直到写好 job_id，这里会等它写完。
            with self.store.lock:
                current = self.store.get_run(info, run_id)
            try:
                return self._run_regenerate(ctx, info, current, requests, run_dir, Path(record.path), expected)
            except Exception as exc:
                current["status"] = "failed"
                current["error"] = str(exc)
                current["finished_at"] = time.time()
                self.store.save_run(info, current)
                raise

        with self.store.lock:
            job = self.job_manager.submit(REGENERATE_JOB, worker)
            run["job_id"] = job.id
            self.store.save_run(info, run)
        return run

    def start_pretranslate(self, info: WorkspaceInfo) -> str | None:
        """后台把工作区里所有提示词 tag 翻译进缓存，界面打开图片时基本不用等。返回任务 id。"""
        if self.llm_client is None or not self.llm_client.available:
            return None
        existing = self._pretranslate_jobs.get(info.id)
        if existing:
            try:
                if self.job_manager.get(existing).status in _ACTIVE_JOB_STATUSES:
                    return existing
            except KeyError:
                pass
        tags: list[str] = []
        for record in self.store.load_index(info).images:
            tags.extend(split_prompt_tags(record.prompt))
            tags.extend(split_prompt_tags(record.negative_prompt))
            for caption in record.char_captions:
                tags.extend(split_prompt_tags(caption.positive))
                tags.extend(split_prompt_tags(caption.negative))
        unique = list(dict.fromkeys(tags))
        client = self.llm_client

        def worker(ctx):
            translated = 0
            for start in range(0, len(unique), _PRETRANSLATE_CHUNK):
                if ctx.cancel_requested:
                    break
                translated += len(translate_tags(client, unique[start : start + _PRETRANSLATE_CHUNK]))
                ctx.emit("progress", {"done": min(start + _PRETRANSLATE_CHUNK, len(unique)), "total": len(unique)})
            return {"total": len(unique), "translated": translated}

        job = self.job_manager.submit(PRETRANSLATE_JOB, worker)
        self._pretranslate_jobs[info.id] = job.id
        return job.id

    def reconcile_run(self, info: WorkspaceInfo, run: dict[str, Any]) -> dict[str, Any]:
        """后端重启后任务线程没了，run.json 还停在 running：标成 interrupted，界面不再一直转圈。"""
        if run.get("status") not in {"queued", "running"}:
            return run
        job_id = run.get("job_id")
        try:
            job_status = self.job_manager.get(job_id).status if job_id else None
        except KeyError:
            job_status = None
        if job_status in {"queued", "running", "cancelling"}:
            return run
        # 读文件和查任务状态之间任务可能刚好跑完：重读一次，确认 run.json 真的停在半路才改。
        with self.store.lock:
            try:
                run = self.store.get_run(info, str(run["id"]))
            except KeyError:
                return run
            if run.get("status") not in {"queued", "running"}:
                return run
            return self._mark_interrupted(info, run)

    def _mark_interrupted(self, info: WorkspaceInfo, run: dict[str, Any]) -> dict[str, Any]:
        run["status"] = "interrupted"
        for item in run.get("items") or []:
            if item.get("status") in {"queued", "running"}:
                item["status"] = "interrupted"
        self.store.save_run(info, run)
        return run

    def _run_regenerate(
        self,
        ctx: Any,
        info: WorkspaceInfo,
        run: dict[str, Any],
        requests: list[dict[str, Any]],
        run_dir: Path,
        source_path: Path,
        expected: list[str],
    ) -> dict[str, Any]:
        run["status"] = "running"
        self.store.save_run(info, run)
        for item, request in zip(run["items"], requests):
            if ctx.cancel_requested:
                item["status"] = "cancelled"
                continue
            item["status"] = "running"
            self.store.save_run(info, run)
            ctx.emit("item_started", {"index": item["index"], "seed": item["seed"]})
            try:
                with self._generate_lock:
                    result = self.generation_api.generate(
                        {"render_request": request, "output_dir": str(run_dir), "on_progress": ctx.emit}
                    )
                images = result.get("images") or []
                if not images:
                    raise RuntimeError("Generation returned no images")
                image_path = Path(str(images[0]["path"]))
                item["image_path"] = str(image_path)
                item["status"] = "succeeded"
                item["compare"] = compare_with_source(source_path, image_path, expected_keys=expected)
            except Exception as exc:  # 单张失败不影响后面的张数
                logger.warning("Style Lab regenerate item failed: %s", exc)
                item["status"] = "failed"
                item["error"] = friendly_error(str(exc))
                item["error_detail"] = str(exc)
            self.store.save_run(info, run)
            ctx.set_result(copy.deepcopy(run))
            ctx.emit("item_finished", {"index": item["index"], "status": item["status"]})
        statuses = {item["status"] for item in run["items"]}
        if statuses == {"succeeded"}:
            run["status"] = "succeeded"
        elif "succeeded" in statuses:
            run["status"] = "partial"
        elif "cancelled" in statuses:
            run["status"] = "cancelled"
        else:
            run["status"] = "failed"
        run["finished_at"] = time.time()
        self.store.save_run(info, run)
        return copy.deepcopy(run)


_KNOWN_ERRORS = (
    ("HTTP 401", "NovelAI token 无效或已过期（HTTP 401），请更新 configs/local.yaml 里的 novelai.access_token。"),
    ("HTTP 402", "NovelAI 拒绝了请求（HTTP 402）：Anlas 不足，或当前订阅不支持这组参数。"),
    ("HTTP 429", "NovelAI 限流（HTTP 429），稍后再试。"),
    ("Missing NovelAI token", "没有配置 NovelAI token：在 configs/local.yaml 填写 novelai.access_token。"),
)


def friendly_error(message: str) -> str:
    """常见的 NovelAI 错误换成能直接照做的说明；其余保留原文。原文另存在 error_detail。"""
    for marker, text in _KNOWN_ERRORS:
        if marker in message:
            return text
    return message


def _source_warnings(flags: list[str]) -> list[str]:
    warnings: list[str] = []
    if "inpaint" in flags or "img2img" in flags:
        warnings.append("源图是局部重绘或图生图，元数据里没有底图，无法完全复现。")
    if "vibe_missing" in flags:
        warnings.append("源图用了 vibe 但没有内嵌参考图，生成时缺少 vibe。")
    if "director_ref" in flags:
        warnings.append("源图用了角色参考（director reference），能否复现取决于参考图是否内嵌。")
    return warnings
