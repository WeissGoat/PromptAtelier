from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any

from tags_machine_core.logging_config import get_logger

from tags_machine_core.llm import translate_tags

from .classify import classify_tags
from .compare import compare_with_source
from .grouping import build_groups, workspace_tags
from .metadata import ImageRecord
from .recipe import Recipe, RecipeStore, artist_node, character_prompts_param, recipe_from_image, tokens_text
from .regenerate import RegenSettings, build_regen_request, expected_diff_keys, plan_seeds
from .workspace import RUN_SCHEMA, WorkspaceInfo, WorkspaceStore


logger = get_logger(__name__)

REGENERATE_JOB = "style_lab_regenerate"
RECIPE_JOB = "style_lab_recipe"
ANALYSIS_JOB = "style_lab_analysis"
_ANALYSIS_CHUNK = 160
_ACTIVE_JOB_STATUSES = {"queued", "running", "cancelling"}


class StyleLabService:
    def __init__(self, *, store: WorkspaceStore, job_manager: Any, generation_api: Any, llm_client: Any = None):
        self.store = store
        self.job_manager = job_manager
        self.generation_api = generation_api
        self.llm_client = llm_client
        self._analysis_jobs: dict[str, str] = {}
        # 每个任务各跑一个线程；同一账号并发请求 NovelAI 会 429，所以 Style Lab 的出图串行执行。
        self._generate_lock = threading.Lock()

    def start_regenerate(self, info: WorkspaceInfo, image_id: str, settings: RegenSettings) -> dict[str, Any]:
        """原参重生：逐张串行出图，每张出完立刻和源图对照并写回 run.json。"""
        record = self.store.find_image(info, image_id)
        if not record.has_metadata:
            raise ValueError(f"Image has no NovelAI metadata: {record.rel_path}")
        seeds = plan_seeds(settings, record.seed)
        requests = [build_regen_request(record, settings, seed) for seed in seeds]
        return self._start_run(
            info,
            record,
            kind="regenerate",
            settings=settings,
            seeds=seeds,
            requests=requests,
            expected=sorted(expected_diff_keys(settings, record)),
        )

    # ---- 配方 ----

    def recipes(self, info: WorkspaceInfo) -> RecipeStore:
        return RecipeStore(Path(info.data_dir))

    def create_recipe(
        self, info: WorkspaceInfo, image_id: str, *, name: str | None = None, group_id: str | None = None
    ) -> Recipe:
        record = self.store.find_image(info, image_id)
        if not record.has_metadata:
            raise ValueError(f"Image has no NovelAI metadata: {record.rel_path}")
        return self.recipes(info).create(recipe_from_image(record, name=name, group_id=group_id))

    def recipe_render_request(
        self,
        info: WorkspaceInfo,
        recipe: Recipe,
        *,
        seed: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        """配方 -> 和导出后的 artist 完全一致的出图请求（走正式的 compose -> render 链路，不联网）。"""
        record = self._recipe_source(info, recipe)
        params: dict[str, Any] = {"size": "custom", "n_samples": 1}
        character = character_prompts_param(recipe)
        if character:
            params["character_prompts"] = character
        payload = {
            "compose": {"prompt": tokens_text(recipe.subject).strip(" ,"), "negative": ""},
            "render": {
                "backend": "novelai",
                "artist": artist_node(recipe, source_path=record.path if record else None),
                "width": width or (record.width if record else None) or 1024,
                "height": height or (record.height if record else None) or 1024,
                "seed": seed,
                "params": params,
            },
        }
        result = self.generation_api.compose_render_plan(payload)
        request = dict(result["render_request"])
        request["meta"] = {**(request.get("meta") or {}), "source": "style_lab_recipe", "recipe_id": recipe.id}
        return request

    def preview_recipe(self, info: WorkspaceInfo, recipe: Recipe) -> dict[str, Any]:
        request = self.recipe_render_request(info, recipe, seed=0)
        params = request.get("params") or {}
        positive = (params.get("v4_prompt") or {}).get("caption") or {}
        negative = (params.get("v4_negative_prompt") or {}).get("caption") or {}
        return {
            "prompt": request.get("prompt") or "",
            "negative_prompt": request.get("negative_prompt") or "",
            "char_captions": [item.get("char_caption", "") for item in positive.get("char_captions") or []],
            "negative_char_captions": [item.get("char_caption", "") for item in negative.get("char_captions") or []],
            "character_prompts": (request.get("meta") or {}).get("character_prompts"),
            "model": request.get("model"),
            "size": request.get("size"),
            "params": {key: params.get(key) for key in ("sampler", "steps", "scale", "cfg_rescale", "noise_schedule")},
            "vibe_count": len(params.get("reference_image_multiple") or []),
        }

    def start_recipe_run(self, info: WorkspaceInfo, recipe_id: str, settings: RegenSettings) -> dict[str, Any]:
        recipe = self.recipes(info).get(recipe_id)
        record = self._recipe_source(info, recipe)
        seeds = plan_seeds(settings, record.seed if record else None)
        width = settings.width if settings.size_mode == "custom" else None
        height = settings.height if settings.size_mode == "custom" else None
        requests = [
            self.recipe_render_request(info, recipe, seed=seed, width=width, height=height) for seed in seeds
        ]
        return self._start_run(
            info,
            record,
            kind="recipe",
            settings=settings,
            seeds=seeds,
            requests=requests,
            expected=[],
            extra={"recipe": {"id": recipe.id, "version": recipe.version, "name": recipe.name}},
        )

    def _recipe_source(self, info: WorkspaceInfo, recipe: Recipe) -> ImageRecord | None:
        if not recipe.source_image_id:
            return None
        try:
            return self.store.find_image(info, recipe.source_image_id)
        except KeyError:
            return None

    # ---- 运行 ----

    def _start_run(
        self,
        info: WorkspaceInfo,
        record: ImageRecord | None,
        *,
        kind: str,
        settings: RegenSettings,
        seeds: list[int],
        requests: list[dict[str, Any]],
        expected: list[str],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id, run_dir = self.store.new_run_dir(info)
        run: dict[str, Any] = {
            "schema": RUN_SCHEMA,
            "id": run_id,
            "kind": kind,
            "status": "queued",
            "created_at": time.time(),
            "finished_at": None,
            "job_id": None,
            "source": (
                {"image_id": record.id, "path": record.path, "rel_path": record.rel_path} if record else None
            ),
            "settings": settings.model_dump(mode="json"),
            "expected_diff_keys": expected,
            "warnings": _source_warnings(record.flags) if record and kind == "regenerate" else [],
            "items": [{"index": index, "seed": seed, "status": "queued"} for index, seed in enumerate(seeds)],
            **(extra or {}),
        }
        source_path = Path(record.path) if record else None

        def worker(ctx):
            # 任务线程只用自己从磁盘读出的副本；提交方持有 store 锁直到写好 job_id，这里会等它写完。
            with self.store.lock:
                current = self.store.get_run(info, run_id)
            try:
                return self._run_items(ctx, info, current, requests, run_dir, source_path, expected)
            except Exception as exc:
                current["status"] = "failed"
                current["error"] = str(exc)
                current["finished_at"] = time.time()
                self.store.save_run(info, current)
                raise

        with self.store.lock:
            job = self.job_manager.submit(REGENERATE_JOB if kind == "regenerate" else RECIPE_JOB, worker)
            run["job_id"] = job.id
            self.store.save_run(info, run)
        return run

    def start_analysis(self, info: WorkspaceInfo) -> str | None:
        """后台分析：把全部提示词 tag 翻译进缓存，并给正向 tag 分类（用于自动分组和划分建议）。返回任务 id。"""
        if self.llm_client is None or not self.llm_client.available:
            return None
        existing = self._analysis_jobs.get(info.id)
        if existing:
            try:
                if self.job_manager.get(existing).status in _ACTIVE_JOB_STATUSES:
                    return existing
            except KeyError:
                pass
        texts, tags = workspace_tags(self.store.load_index(info).images)
        client = self.llm_client
        total = len(texts) + len(tags)

        def worker(ctx):
            done = translated = classified = 0
            for stage, items in (("translate", texts), ("classify", tags)):
                for start in range(0, len(items), _ANALYSIS_CHUNK):
                    if ctx.cancel_requested:
                        return {"total": total, "translated": translated, "classified": classified}
                    chunk = items[start : start + _ANALYSIS_CHUNK]
                    if stage == "translate":
                        translated += len(translate_tags(client, chunk))
                    else:
                        classified += len(classify_tags(client, chunk))
                    done += len(chunk)
                    ctx.emit("progress", {"stage": stage, "done": done, "total": total})
            return {"total": total, "translated": translated, "classified": classified}

        job = self.job_manager.submit(ANALYSIS_JOB, worker)
        self._analysis_jobs[info.id] = job.id
        return job.id

    def analysis(self, info: WorkspaceInfo) -> dict[str, Any]:
        """当前的分类和分组（只读缓存，不调用 LLM）；分析任务还在跑时结果会逐步变完整。"""
        images = self.store.load_index(info).images
        _, tags = workspace_tags(images)
        categories = classify_tags(self.llm_client if self.llm_client and self.llm_client.available else None, tags, fetch=False)
        job_id = self._analysis_jobs.get(info.id)
        running = False
        if job_id:
            try:
                running = self.job_manager.get(job_id).status in _ACTIVE_JOB_STATUSES
            except KeyError:
                running = False
        return {
            "categories": categories,
            "classified": len(categories),
            "total_tags": len(tags),
            "job_id": job_id if running else None,
            "groups": build_groups(images, categories),
        }

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

    def _run_items(
        self,
        ctx: Any,
        info: WorkspaceInfo,
        run: dict[str, Any],
        requests: list[dict[str, Any]],
        run_dir: Path,
        source_path: Path | None,
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
                if source_path is not None:
                    item["compare"] = compare_with_source(source_path, image_path, expected_keys=expected)
                    if run["kind"] != "regenerate":
                        # 配方出图和原图本来就是不同提示词，只看相似度和提示词差异，不下“链路”结论。
                        item["compare"]["verdict"] = "reference"
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
