"""Analysis context and resumable preparation. This module never submits generation."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .custom_groups import (
    CustomGroups,
    CustomGroupStore,
    GroupConflictError,
    artifact_path,
    digest,
    image_fingerprint,
    member_ids,
    post_key,
    source_problems,
)
from .recipe import Recipe
from .workspace import _atomic_write


class PreparationService:
    def __init__(self, service, info):
        self.service, self.info = service, info
        self.store = service.store
        self.groups = CustomGroupStore(self.store, info)

    def context(self, offset: int = 0, limit: int = 20) -> dict:
        posts: dict[str, list] = {}
        for image in self.store.load_index(self.info).images:
            posts.setdefault(post_key(image), []).append(image)
        keys = sorted(posts)
        return {
            "workspace_id": self.info.id,
            "total_posts": len(keys),
            "offset": offset,
            "next_offset": offset + limit if offset + limit < len(keys) else None,
            "posts": [
                {
                    "key": key,
                    "images": [
                        {**image.model_dump(mode="json"), "problems": source_problems(image)}
                        for image in posts[key]
                    ],
                }
                for key in keys[offset : offset + limit]
            ],
            "custom_groups": self.groups.payload(),
            "recipes": [
                {
                    "id": r.id,
                    "name": r.name,
                    "source_group": r.source_group,
                    "source_image_id": r.source_image_id,
                    "preparation": self.status(r),
                }
                for r in self.service.recipes(self.info).list()
            ],
        }

    def status(self, recipe: Recipe) -> dict:
        result = dict(recipe.preparation or {})
        result.setdefault(
            "status",
            "ready"
            if recipe.stage == "edit" and (recipe.prefix or recipe.suffix)
            else "needs_review",
        )
        image = self.service._recipe_source(self.info, recipe)
        if image is None or not Path(image.path).is_file():
            return {**result, "status": "source_missing", "reason": "代表源图不存在"}
        if result.get("source_fingerprint") and result["source_fingerprint"] != image_fingerprint(
            image
        ):
            return {**result, "status": "stale", "reason": "代表源图已变化，请重扫后重新检查配方"}
        problems = source_problems(image)
        if problems:
            return {**result, "status": "needs_review", "reason": "；".join(problems)}
        if recipe.stage != "edit" or not recipe.locked or not (recipe.prefix or recipe.suffix):
            return {**result, "status": "needs_review", "reason": "画风尚未完成划分并锁定"}
        if (
            recipe.source_group
            and recipe.source_group.kind == "custom"
            and recipe.source_image_id not in member_ids(self.groups.load(), recipe.source_group.id)
        ):
            return {**result, "status": "needs_review", "reason": "来源组已删除或代表图已移出该组"}
        return result

    def validate_recipe(self, recipe: Recipe, groups: CustomGroups | None = None) -> None:
        image = self.service._recipe_source(self.info, recipe)
        if image is None:
            raise ValueError("配方必须指定工作区内的代表源图")
        if (
            recipe.source_group
            and recipe.source_group.kind == "custom"
            and image.id not in member_ids(groups or self.groups.load(), recipe.source_group.id)
        ):
            raise ValueError("配方代表图不属于来源自定义组")
        if (recipe.preparation or {}).get("status") == "ready":
            if source_problems(image):
                raise ValueError("代表图有复现限制，不能标为 ready")
            if recipe.stage != "edit" or not recipe.locked or not (recipe.prefix or recipe.suffix):
                raise ValueError("完成画风划分并锁定后才能标为 ready")
            self.service.preview_recipe(self.info, recipe)

    def get(self, identifier: str) -> dict:
        path = artifact_path(self.info, "analyses", identifier)
        with self.store.lock:
            if not path.exists():
                raise KeyError(identifier)
            return json.loads(path.read_text(encoding="utf-8"))

    def apply(self, data: dict[str, Any]) -> dict:
        identifier = str(data.get("id") or "")
        if not identifier:
            raise ValueError("请提供稳定的准备任务 id，以便中断后恢复同一请求")
        path = artifact_path(self.info, "analyses", identifier)
        fingerprint = digest(data)
        with self.store.lock:
            if path.exists():
                record = self.get(identifier)
                if record["request_hash"] != fingerprint:
                    raise GroupConflictError("准备任务 id 已用于不同内容，请使用新 id")
                if record["status"] == "succeeded":
                    return record
            else:
                record = {
                    "id": identifier,
                    "request_hash": fingerprint,
                    "status": "applying",
                    "created_at": time.time(),
                    "summary": str(data.get("summary") or ""),
                    "rules_version": str(data.get("rules_version") or "style-lab-analysis/v1"),
                    "groups_applied": False,
                    "results": [],
                    "request": data,
                }
            doc = (
                CustomGroups.model_validate(data["custom_groups"])
                if data.get("custom_groups") is not None
                else None
            )
            recipes = [Recipe.model_validate(value) for value in data.get("recipes", [])]
            if len({recipe.id for recipe in recipes}) != len(recipes):
                raise ValueError("配方 id 重复")
            if (
                doc
                and not record["groups_applied"]
                and self.groups.load().operation_id != identifier
            ):
                self.groups.validate(doc, actor="agent")
            validation_doc = self.groups.load() if record["groups_applied"] else doc
            for recipe in recipes:
                self.validate_recipe(recipe, validation_doc)
            self._save(path, record)
            if doc and not record["groups_applied"]:
                if self.groups.load().operation_id != identifier:
                    self.groups.save(doc, actor="agent", operation_id=identifier)
                record["groups_applied"] = True
                self._save(path, record)
            completed = {
                item["recipe_id"] for item in record["results"] if item["status"] == "created"
            }
            record["results"] = [item for item in record["results"] if item["status"] == "created"]
            for recipe in recipes:
                if recipe.id in completed:
                    continue
                try:
                    try:
                        existing = self.service.recipes(self.info).get(recipe.id)
                    except KeyError:
                        existing = None
                    if existing:
                        if (existing.preparation or {}).get("analysis_id") != identifier:
                            raise GroupConflictError("配方 id 已存在，不覆盖已有配方")
                    else:
                        image = self.service._recipe_source(self.info, recipe)
                        recipe.preparation = {
                            **(recipe.preparation or {}),
                            "analysis_id": identifier,
                            "status": (recipe.preparation or {}).get("status", "needs_review"),
                            "source_fingerprint": image_fingerprint(image),
                        }
                        recipe.version = 1
                        recipe.created_at = recipe.updated_at = time.time()
                        self.service.recipes(self.info).create(recipe)
                    record["results"].append({"recipe_id": recipe.id, "status": "created"})
                except (ValueError, OSError) as exc:
                    record["results"].append(
                        {"recipe_id": recipe.id, "status": "failed", "error": str(exc)}
                    )
                self._save(path, record)
            record["status"] = (
                "partial"
                if any(item["status"] == "failed" for item in record["results"])
                else "succeeded"
            )
            self._save(path, record)
            return record

    @staticmethod
    def _save(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))
