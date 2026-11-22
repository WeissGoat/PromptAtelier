"""Explicit, immutable-snapshot generation plans; preparation never calls this executor."""

from __future__ import annotations

import copy
import json
import logging
import time
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from .custom_groups import (
    CustomGroupStore,
    GroupConflictError,
    artifact_path,
    digest,
    image_fingerprint,
)
from .preparation import PreparationService
from .recipe import Recipe
from .regenerate import RegenSettings, build_regen_request
from .service import DuplicateRequestError, request_fingerprint
from .workspace import _atomic_write

ACTIVE = {"queued", "running", "cancelling"}
logger = logging.getLogger(__name__)


class TestVariant(BaseModel):
    __test__ = False
    recipe_id: str
    label: str = "角色/动作测试"
    recipe: Recipe


class TestPlanRequest(BaseModel):
    __test__ = False
    recipe_ids: list[str] = Field(default_factory=list)
    group_ids: list[str] = Field(default_factory=list)
    include_materials: bool = True
    variant_limit: int = Field(default=3, ge=0, le=30)
    variants: list[TestVariant] = Field(default_factory=list)
    continue_on_drift: bool = False


class TestPlanService:
    __test__ = False

    def __init__(self, service, info):
        self.service, self.info = service, info
        self.store = service.store

    def _path(self, identifier):
        return artifact_path(self.info, "test_plans", identifier)

    def _save(self, plan):
        path = self._path(plan["id"])
        with self.store.lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, json.dumps(plan, ensure_ascii=False, indent=2))

    def get(self, identifier):
        with self.store.lock:
            path = self._path(identifier)
            if not path.exists():
                raise KeyError(identifier)
            plan = json.loads(path.read_text(encoding="utf-8"))
            if plan["status"] in ACTIVE:
                try:
                    status = self.service.job_manager.get(plan["job_id"]).status
                except KeyError:
                    status = "interrupted"
                if status not in ACTIVE:
                    plan["status"] = "interrupted"
                    self._save(plan)
            return plan

    def list(self):
        root = Path(self.info.data_dir) / "test_plans"
        return sorted(
            [self.get(path.stem) for path in root.glob("*.json")],
            key=lambda p: p["created_at"],
            reverse=True,
        )

    @staticmethod
    def public(plan):
        result = copy.deepcopy(plan)
        for item in result["items"]:
            request = item.pop("request", {})
            item["preview"] = {
                key: request.get(key)
                for key in ("prompt", "negative_prompt", "seed", "size", "model")
            }
            params = request.get("params") or {}
            item["preview"]["char_captions"] = (
                (params.get("v4_prompt") or {}).get("caption") or {}
            ).get("char_captions", [])
        return result

    def create(self, data, shelf):
        data = TestPlanRequest.model_validate(data).model_dump(mode="json", by_alias=True)
        with self.store.lock:
            recipes = self.service.recipes(self.info).list()
            selected = set(data.get("recipe_ids") or [])
            group_ids = set(data.get("group_ids") or [])
            doc = CustomGroupStore(self.store, self.info).load()
            known_groups = {group.id for group in doc.groups}
            if group_ids - known_groups:
                raise ValueError("选中的自定义组不存在")
            expanded_groups = group_ids | {
                group.id for group in doc.groups if group.parent_id in group_ids
            }
            for recipe in recipes:
                if (
                    recipe.source_group
                    and recipe.source_group.kind == "custom"
                    and recipe.source_group.id in expanded_groups
                ):
                    selected.add(recipe.id)
            if not selected or selected - {recipe.id for recipe in recipes}:
                raise ValueError("请明确选择存在的配方或包含配方的自定义组")
            limit = int(data.get("variant_limit", 3))
            if not 0 <= limit <= 30:
                raise ValueError("variant_limit 必须在 0 到 30 之间")
            plan = {
                "id": "test_" + uuid.uuid4().hex[:12],
                "status": "draft",
                "created_at": time.time(),
                "job_id": None,
                "recipe_ids": sorted(selected),
                "group_ids": sorted(group_ids),
                "recipes": {},
                "sources": {},
                "shelf": shelf.model_dump(mode="json"),
                "items": [],
                "missing_variants": [],
                "continue_on_drift": bool(data.get("continue_on_drift", False)),
            }
            variants = data.get("variants") or []
            if any(variant.get("recipe_id") not in selected for variant in variants):
                raise ValueError("测试变体包含未选中的配方")
            regenerations = {}
            for recipe in sorted(recipes, key=lambda value: value.id):
                if recipe.id not in selected:
                    continue
                state = PreparationService(self.service, self.info).status(recipe)
                if state["status"] != "ready":
                    raise ValueError(
                        f"配方 {recipe.name} 尚不能测试：{state.get('reason') or state['status']}"
                    )
                source = self.service._recipe_source(self.info, recipe)
                plan["recipes"][recipe.id] = {
                    "hash": digest(recipe.model_dump(mode="json", by_alias=True)),
                    "name": recipe.name,
                }
                plan["sources"][source.id] = image_fingerprint(source)
                if source.id not in regenerations:
                    item = self._item(
                        plan,
                        "regenerate",
                        recipe,
                        source,
                        build_regen_request(source, RegenSettings(), source.seed),
                        "原参重生",
                    )
                    regenerations[source.id] = item["id"]
                baseline = self._item(
                    plan,
                    "recipe",
                    recipe,
                    source,
                    self.service.recipe_render_request(self.info, recipe, seed=source.seed),
                    "配方原图内容",
                    regenerations[source.id],
                )
                seen = {baseline["request_hash"]}
                choices = [variant for variant in variants if variant["recipe_id"] == recipe.id]
                if len(choices) > limit:
                    raise ValueError("变体数量超过本计划的 variant_limit")
                if (
                    limit
                    and data.get("include_materials", True)
                    and shelf.materials
                    and not choices
                ):
                    plan["missing_variants"].append(recipe.id)
                for variant in choices:
                    snapshot = Recipe.model_validate(variant["recipe"])
                    allowed_content = {"name", "subject", "character", "materials", "notes"}
                    saved_values = recipe.model_dump(mode="json", by_alias=True)
                    snapshot_values = snapshot.model_dump(mode="json", by_alias=True)
                    if any(
                        snapshot_values[key] != value
                        for key, value in saved_values.items()
                        if key not in allowed_content
                    ):
                        raise ValueError("变体只能改测试内容，不能更换配方、源图或画风签名")
                    allowed = {
                        (material.role, material.ref): material for material in shelf.materials
                    }
                    if data.get("include_materials", True):
                        if shelf.materials and not snapshot.materials:
                            raise ValueError("素材变体必须记录本次使用的卡片与 exclusions")
                        for material in snapshot.materials:
                            if (material.role, material.ref) not in allowed or material != allowed[
                                (material.role, material.ref)
                            ]:
                                raise ValueError("变体素材及 exclusions 必须来自本次素材架快照")
                    item = self._item(
                        plan,
                        "recipe",
                        snapshot,
                        source,
                        self.service.recipe_render_request(self.info, snapshot, seed=source.seed),
                        str(variant.get("label") or "角色/动作测试"),
                        baseline["id"],
                    )
                    item["role"] = "variant"
                    if item["request_hash"] in seen:
                        raise ValueError("变体与原图内容或其他变体重复，请提供不同测试内容")
                    seen.add(item["request_hash"])
            if plan["missing_variants"]:
                plan["status"] = "awaiting_content"
            plan["estimated_count"] = len(plan["items"])
            plan["reuse_count"] = sum(self._reusable(item) is not None for item in plan["items"])
            self._save(plan)
            return plan

    def _item(self, plan, kind, recipe, source, request, label, dependency=None):
        item = {
            "id": "item_" + uuid.uuid4().hex[:10],
            "kind": kind,
            "recipe_id": recipe.id,
            "source_image_id": source.id,
            "source_fingerprint": image_fingerprint(source),
            "label": label,
            "role": "regenerate" if kind == "regenerate" else "baseline",
            "dependency": dependency,
            "status": "pending",
            "request": request,
            "request_hash": request_fingerprint(kind, [request]),
            "recipe_snapshot": recipe.model_dump(mode="json", by_alias=True)
            if kind == "recipe"
            else None,
        }
        plan["items"].append(item)
        return item

    def _reusable(self, item):
        for run in self.store.list_runs(self.info, image_id=item["source_image_id"]):
            if (
                run.get("request_hash") == item["request_hash"]
                and run.get("status") == "succeeded"
                and run.get("source_fingerprint") == item["source_fingerprint"]
                and run.get("items")
                and all(Path(result.get("image_path") or "").is_file() for result in run["items"])
            ):
                return run
        return None

    def start(self, identifier):
        with self.store.lock:
            plan = self.get(identifier)
            if plan["status"] in ACTIVE or plan["status"] == "succeeded":
                return plan
            if plan["missing_variants"]:
                raise ValueError(
                    "素材测试内容尚未准备；先由 Agent/编辑器准备变体，或新建仅基准测试计划"
                )
            for recipe_id, reference in plan["recipes"].items():
                recipe = self.service.recipes(self.info).get(recipe_id)
                if digest(recipe.model_dump(mode="json", by_alias=True)) != reference["hash"]:
                    raise GroupConflictError("配方内容已变化，请重新建立测试计划")
            for source_id, fingerprint in plan["sources"].items():
                source = self.store.find_image(self.info, source_id)
                if image_fingerprint(source) != fingerprint:
                    raise GroupConflictError("代表源图已变化，请重扫后重新建立测试计划")
            plan["status"] = "queued"
            # Hold the shared store lock until job_id and the initial plan are durable.
            job = self.service.job_manager.submit(
                "style_lab_test_plan", lambda ctx: self._execute(identifier, ctx)
            )
            plan["job_id"] = job.id
            self._save(plan)
            return plan

    def _execute(self, identifier, ctx):
        with self.store.lock:
            plan = self.get(identifier)
        plan["status"] = "running"
        self._save(plan)
        by_id = {item["id"]: item for item in plan["items"]}
        try:
            for item in plan["items"]:
                if ctx.cancel_requested:
                    plan["status"] = "cancelled"
                    break
                dependency = by_id.get(item.get("dependency"))
                if dependency and (
                    dependency["status"] != "succeeded" or dependency.get("blocks_following")
                ):
                    item.update(status="skipped", error="前置原参/基准测试未通过，需先检查")
                    self._save(plan)
                    continue
                try:
                    run = self._existing_or_submit(plan, item)
                    item.update(status="running", run_id=run["id"])
                    self._save(plan)
                    while run["status"] in ACTIVE:
                        if (
                            ctx.cancel_requested
                            and run.get("test_plan_id") == identifier
                            and run.get("job_id")
                        ):
                            self.service.job_manager.cancel(run["job_id"])
                        self.service.job_manager.wait(run["job_id"], timeout=0.2)
                        run = self.service.reconcile_run(
                            self.info, self.store.get_run(self.info, run["id"])
                        )
                    item.update(status=run["status"], results=run["items"])
                    if item["kind"] == "regenerate" and not plan["continue_on_drift"]:
                        item["blocks_following"] = any(
                            (result.get("compare") or {}).get("verdict") != "match"
                            for result in run["items"]
                        )
                except Exception as exc:
                    logger.exception("Style Lab test item failed: %s", item["id"])
                    item.update(status="failed", error=str(exc))
                self._save(plan)
                ctx.set_result(self.public(plan))
            if plan["status"] != "cancelled":
                statuses = {item["status"] for item in plan["items"]}
                plan["status"] = (
                    "succeeded"
                    if statuses == {"succeeded"}
                    else "partial"
                    if "succeeded" in statuses
                    else "failed"
                )
        except Exception as exc:
            logger.exception("Style Lab test plan failed: %s", identifier)
            plan.update(status="failed", error=str(exc))
        plan["finished_at"] = time.time()
        self._save(plan)
        return self.public(plan)

    def _existing_or_submit(self, plan, item):
        # Recover the previously linked run before considering a new submission.
        if item.get("run_id"):
            try:
                run = self.service.reconcile_run(
                    self.info, self.store.get_run(self.info, item["run_id"])
                )
            except KeyError:
                run = None
            if run and (
                run["status"] in ACTIVE
                or (
                    run["status"] == "succeeded"
                    and run.get("items")
                    and all(
                        Path(result.get("image_path") or "").is_file() for result in run["items"]
                    )
                )
            ):
                return run
        reusable = self._reusable(item)
        if reusable:
            item["reused"] = True
            return self._reuse_record(plan, item, reusable)
        source = self.store.find_image(self.info, item["source_image_id"])
        if image_fingerprint(source) != item["source_fingerprint"]:
            raise ValueError("执行期间源图发生变化，已停止该项")
        recipe = item["recipe_snapshot"]
        extra = {
            "test_plan_id": plan["id"],
            "test_label": item["label"],
            "recipe_snapshot": recipe,
            "source_fingerprint": item["source_fingerprint"],
        }
        if recipe:
            extra["recipe"] = {key: recipe[key] for key in ("id", "name", "version")}
        kwargs = {
            "kind": item["kind"],
            "settings": RegenSettings(),
            "seeds": [source.seed],
            "requests": [item["request"]],
            "expected": [],
            "extra": extra,
        }
        try:
            return self.service._start_run(self.info, source, **kwargs)
        except DuplicateRequestError as exc:
            previous = exc.previous
            if previous["status"] in ACTIVE:
                return previous
            if (
                previous.get("items")
                and all(
                    Path(result.get("image_path") or "").is_file() for result in previous["items"]
                )
                and Path(source.path).stat().st_mtime <= previous.get("created_at", 0)
            ):
                item["reused"] = True
                return self._reuse_record(plan, item, previous)
            # A missing result is repaired, rather than requesting another candidate.
            return self.service._start_run(self.info, source, **kwargs, force=True)

    def _reuse_record(self, plan, item, previous):
        # Keep reused images discoverable from the selected recipe's own history.
        run = copy.deepcopy(previous)
        run_id, _ = self.store.new_run_dir(self.info)
        run.update(
            id=run_id,
            job_id=None,
            created_at=time.time(),
            finished_at=time.time(),
            test_plan_id=plan["id"],
            test_label=item["label"],
            reuse_of_run_id=previous["id"],
            source_fingerprint=item["source_fingerprint"],
            recipe_snapshot=item["recipe_snapshot"],
        )
        if item["recipe_snapshot"]:
            run["recipe"] = {key: item["recipe_snapshot"][key] for key in ("id", "name", "version")}
        self.store.save_run(self.info, run)
        return run
