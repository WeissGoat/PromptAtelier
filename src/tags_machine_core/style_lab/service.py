from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from tags_machine_core.logging_config import get_logger

from tags_machine_core.llm import translate_tags

from .artist_test import (
    ArtistTestSettings,
    matrix_cells,
    matrix_payload,
    pick_regression_images,
    plan_seed,
    regression_payload,
    shared_random_seed,
    strip_style,
    style_norms,
    subject_norms,
)
from .classify import classify_tags
from .compare import compare_with_source
from .export import ArtistExporter, ExportError, ExportLog, ExportRequest, suggest_author
from .grouping import build_groups, workspace_tags
from .metadata import ImageRecord
from .recipe import Recipe, RecipeStore, artist_node, character_prompts_param, recipe_from_image, tokens_text
from .regenerate import RegenSettings, build_regen_request, expected_diff_keys, plan_seeds
from .workspace import RUN_SCHEMA, WorkspaceInfo, WorkspaceStore


logger = get_logger(__name__)

REGENERATE_JOB = "style_lab_regenerate"
RECIPE_JOB = "style_lab_recipe"
ARTIST_TEST_JOB = "style_lab_artist_test"
ANALYSIS_JOB = "style_lab_analysis"
_ANALYSIS_CHUNK = 160
_ACTIVE_JOB_STATUSES = {"queued", "running", "cancelling"}
# 上一次同样的请求还在跑或已经全部出完时拦下；失败、取消、部分失败的允许原样重试。
_DUPLICATE_BLOCKING_STATUSES = {"queued", "running", "succeeded"}


class DuplicateRequestError(RuntimeError):
    """和上一次（同一张图或同一个配方、同一种出图）的请求完全相同。"""

    def __init__(self, previous: dict[str, Any]):
        super().__init__("和上一次的请求完全相同，出图结果也会一样。")
        self.previous = previous


def request_fingerprint(kind: str, requests: list[dict[str, Any]]) -> str:
    """发给 NovelAI 的内容（不含 meta 里的来源记录）的指纹。"""
    body = [{key: value for key, value in request.items() if key != "meta"} for request in requests]
    text = json.dumps([kind, body], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


class StyleLabService:
    def __init__(
        self,
        *,
        store: WorkspaceStore,
        job_manager: Any,
        generation_api: Any,
        llm_client: Any = None,
        artist_root: Path | None = None,
    ):
        self.store = store
        self.job_manager = job_manager
        self.generation_api = generation_api
        self.llm_client = llm_client
        self.exporter = ArtistExporter(artist_root) if artist_root else None
        self._analysis_jobs: dict[str, str] = {}
        # 每个任务各跑一个线程；同一账号并发请求 NovelAI 会 429，所以 Style Lab 的出图串行执行。
        self._generate_lock = threading.Lock()

    def start_regenerate(
        self, info: WorkspaceInfo, image_id: str, settings: RegenSettings, *, force: bool = False
    ) -> dict[str, Any]:
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
            force=force,
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

    def start_recipe_run(
        self, info: WorkspaceInfo, recipe_id: str, settings: RegenSettings, *, force: bool = False
    ) -> dict[str, Any]:
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
            force=force,
        )

    def _recipe_source(self, info: WorkspaceInfo, recipe: Recipe) -> ImageRecord | None:
        if not recipe.source_image_id:
            return None
        try:
            return self.store.find_image(info, recipe.source_image_id)
        except KeyError:
            return None

    # ---- 导出 ----

    def _exporter(self) -> ArtistExporter:
        if self.exporter is None:
            raise ExportError("没有配置 design_root，不知道画风目录在哪里。")
        return self.exporter

    def export_defaults(self, info: WorkspaceInfo, recipe_id: str) -> dict[str, Any]:
        self.recipes(info).get(recipe_id)
        exports = self.exports(info, recipe_id)
        author = suggest_author(info)
        return {
            "author": author,
            "artist_root": str(self._exporter().artist_root),
            "exports": exports,
            "candidates": self._exporter().candidates(author, exports),
        }

    def export_preview(self, info: WorkspaceInfo, recipe_id: str, request: ExportRequest) -> dict[str, Any]:
        recipe = self.recipes(info).get(recipe_id)
        return self._exporter().preview(
            recipe, request, record=self._recipe_source(info, recipe), exports=self.exports(info, recipe_id)
        )

    def export_recipe(
        self, info: WorkspaceInfo, recipe_id: str, request: ExportRequest, *, expected_folder: str | None = None
    ) -> dict[str, Any]:
        recipe = self.recipes(info).get(recipe_id)
        entry = self._exporter().export(
            recipe, request, record=self._recipe_source(info, recipe), info=info, expected_folder=expected_folder
        )
        ExportLog(Path(info.data_dir)).add(entry)
        return {**entry, "exists": True}

    def exports(self, info: WorkspaceInfo, recipe_id: str) -> list[dict[str, Any]]:
        items = ExportLog(Path(info.data_dir)).for_recipe(recipe_id)
        root = self.exporter.artist_root if self.exporter else None
        return [{**item, "exists": bool(root and (root / item["folder"] / "tags.txt").is_file())} for item in items]

    # ---- 用导出的 artist 测试 ----

    def start_artist_test(
        self, info: WorkspaceInfo, recipe_id: str, settings: ArtistTestSettings, *, force: bool = False
    ) -> dict[str, Any]:
        recipe = self.recipes(info).get(recipe_id)
        exporter = self._exporter()
        if not (exporter.artist_root / settings.artist / "tags.txt").is_file():
            raise ValueError(f"画风目录不存在：{settings.artist}")
        record = self._recipe_source(info, recipe)
        shared = shared_random_seed()
        requests: list[dict[str, Any]] = []
        metas: list[dict[str, Any]] = []
        seeds: list[int] = []
        if settings.kind == "regression":
            images = self.store.load_index(info).images
            candidate_ids = settings.image_ids or self._group_image_ids(recipe, images)
            picked = pick_regression_images(
                images,
                candidate_ids,
                first_id=recipe.source_image_id,
                limit=len(settings.image_ids) if settings.image_ids else 4,
            )
            if not picked:
                raise ValueError("没有可用于回归对照的原图（需要有元数据、不是局部重绘或图生图）。")
            categories = self._cached_categories(images)
            norms = style_norms(recipe)
            keep = subject_norms(recipe)
            for image in picked:
                subject, removed = strip_style(image.prompt, norms, categories, keep)
                seed = plan_seed(settings, image.seed, shared)
                seeds.append(seed)
                requests.append(self._plan(regression_payload(settings, image, subject, seed)))
                metas.append(
                    {
                        "label": image.post.post_id if image.post and image.post.post_id else Path(image.path).stem,
                        "source": {"image_id": image.id, "path": image.path, "rel_path": image.rel_path},
                        "subject": subject,
                        "removed": removed,
                    }
                )
        else:
            seed = plan_seed(settings, record.seed if record else None, shared)
            for character, action in matrix_cells(settings):
                seeds.append(seed)
                requests.append(self._plan(matrix_payload(settings, character, action, seed)))
                metas.append({"character": character, "action": action})
        return self._start_run(
            info,
            record,
            kind=settings.kind,
            settings=settings,
            seeds=seeds,
            requests=requests,
            expected=[],
            extra={
                "recipe": {"id": recipe.id, "version": recipe.version, "name": recipe.name},
                "artist": {"folder": settings.artist},
            },
            item_meta=metas,
            force=force,
        )

    def _plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.generation_api.compose_render_plan(payload)
        except Exception as exc:  # noqa: BLE001 - 组合失败直接告诉界面
            raise ValueError(f"拼提示词失败：{exc}") from exc
        request = dict(result["render_request"])
        request["meta"] = {**(request.get("meta") or {}), "source": "style_lab_artist_test"}
        return request

    def _cached_categories(self, images: list[ImageRecord]) -> dict[str, str]:
        _, tags = workspace_tags(images)
        client = self.llm_client if self.llm_client and self.llm_client.available else None
        return classify_tags(client, tags, fetch=False)

    def _group_image_ids(self, recipe: Recipe, images: list[ImageRecord]) -> list[str] | None:
        if not recipe.group_id:
            return None
        for group in build_groups(images, self._cached_categories(images)):
            for candidate in (group, *group.get("children", [])):
                if candidate["id"] == recipe.group_id:
                    return list(candidate["image_ids"])
        return None

    # ---- 运行 ----

    def _start_run(
        self,
        info: WorkspaceInfo,
        record: ImageRecord | None,
        *,
        kind: str,
        settings: RegenSettings | ArtistTestSettings,
        seeds: list[int],
        requests: list[dict[str, Any]],
        expected: list[str],
        extra: dict[str, Any] | None = None,
        item_meta: list[dict[str, Any]] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        fingerprint = request_fingerprint(kind, requests)
        # 查重、建目录、提交任务都在锁里：连点两次时第二次一定能看到第一次。
        with self.store.lock:
            if not force:
                previous = self._previous_run(info, kind, record, extra)
                if (
                    previous
                    and previous.get("request_hash") == fingerprint
                    and previous.get("status") in _DUPLICATE_BLOCKING_STATUSES
                ):
                    raise DuplicateRequestError(previous)
            return self._submit_run(
                info,
                record,
                kind=kind,
                settings=settings,
                seeds=seeds,
                requests=requests,
                expected=expected,
                extra={**(extra or {}), "request_hash": fingerprint},
                item_meta=item_meta,
            )

    def _previous_run(
        self, info: WorkspaceInfo, kind: str, record: ImageRecord | None, extra: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """同一目标（配方出图、测试按配方；原参重生按原图）上一次同类出图。"""
        recipe_id = ((extra or {}).get("recipe") or {}).get("id")
        if recipe_id:
            runs = self.store.list_runs(info, recipe_id=recipe_id)
        elif record is not None:
            runs = self.store.list_runs(info, image_id=record.id)
        else:
            return None
        return next((run for run in runs if run.get("kind") == kind), None)

    def _submit_run(
        self,
        info: WorkspaceInfo,
        record: ImageRecord | None,
        *,
        kind: str,
        settings: RegenSettings | ArtistTestSettings,
        seeds: list[int],
        requests: list[dict[str, Any]],
        expected: list[str],
        extra: dict[str, Any],
        item_meta: list[dict[str, Any]] | None,
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
            "items": [
                {"index": index, "seed": seed, "status": "queued", **(item_meta[index] if item_meta else {})}
                for index, seed in enumerate(seeds)
            ],
            **extra,
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
            job = self.job_manager.submit(_JOB_NAMES.get(kind, ARTIST_TEST_JOB), worker)
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
                # 回归对照每张对照自己的原图；泛化矩阵没有原图可比。
                item_source = Path(item["source"]["path"]) if item.get("source") else source_path
                if item_source is not None and run["kind"] != "matrix":
                    item["compare"] = compare_with_source(item_source, image_path, expected_keys=expected)
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


_JOB_NAMES = {"regenerate": REGENERATE_JOB, "recipe": RECIPE_JOB}

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
