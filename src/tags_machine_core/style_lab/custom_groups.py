"""Persistent, user/agent editable groups. Automatic clustering remains a separate view."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .metadata import ImageRecord
from .workspace import WorkspaceInfo, WorkspaceStore, _atomic_write


class GroupConflictError(ValueError):
    pass


class GroupRef(BaseModel):
    kind: Literal["custom", "auto"]
    id: str


class CustomGroup(BaseModel):
    id: str = Field(
        default_factory=lambda: "cg_" + uuid.uuid4().hex[:12], pattern=r"^cg_[\w-]{1,76}$"
    )
    parent_id: str | None = None
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["style", "review", "archive"] = "style"
    notes: str = ""
    reason: str = ""
    evidence_strength: Literal["strong", "limited", "review"] = "limited"
    evidence_image_ids: list[str] = Field(default_factory=list)
    representative_image_id: str | None = None
    origin_auto_group_id: str | None = None
    order: int = 0
    locked: bool = False
    updated_by: Literal["user", "agent"] = "user"


class CustomGroups(BaseModel):
    revision: int = Field(default=0, ge=0)
    groups: list[CustomGroup] = Field(default_factory=list)
    membership: dict[str, str] = Field(default_factory=dict)
    locked_image_ids: list[str] = Field(default_factory=list)
    updated_at: float | None = None
    operation_id: str | None = None


def image_fingerprint(image: ImageRecord) -> str:
    stat = Path(image.path).stat()
    return digest([image.path, stat.st_size, stat.st_mtime_ns])


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def post_key(image: ImageRecord) -> str:
    # Include the relative directory: equal post basenames in different roots are not one post.
    return (
        image.rel_path.replace("\\", "/").rsplit("/", 1)[0] if image.post else "image:" + image.id
    )


def member_ids(doc: CustomGroups, group_id: str) -> list[str]:
    children = {group.id for group in doc.groups if group.parent_id == group_id}
    return [
        image_id for image_id, target in doc.membership.items() if target in children | {group_id}
    ]


class CustomGroupStore:
    def __init__(self, store: WorkspaceStore, info: WorkspaceInfo):
        self.store, self.info = store, info
        self.path = Path(info.data_dir) / "custom_groups.json"

    def load(self) -> CustomGroups:
        with self.store.lock:
            if not self.path.exists():
                return CustomGroups()
            return CustomGroups.model_validate_json(self.path.read_text(encoding="utf-8"))

    def validate(
        self, doc: CustomGroups, *, actor: str, current: CustomGroups | None = None
    ) -> None:
        current = current or self.load()
        if doc.revision != current.revision:
            raise GroupConflictError("自定义分组已更新，请重新读取后合并修改。")
        groups = {group.id: group for group in doc.groups}
        if len(groups) != len(doc.groups):
            raise ValueError("自定义组 id 重复")
        for group in groups.values():
            if not group.name.strip():
                raise ValueError("组名不能为空")
            if group.parent_id:
                parent = groups.get(group.parent_id)
                if parent is None or parent.id == group.id or parent.parent_id:
                    raise ValueError("只支持家族与子组两级，父组不存在或形成循环")
        parents = {group.parent_id for group in groups.values() if group.parent_id}
        known = {image.id for image in self.store.load_index(self.info).images}
        for image_id, group_id in doc.membership.items():
            if group_id not in groups or group_id in parents:
                raise ValueError("图片必须分配到存在的叶子组")
            if image_id not in known and image_id not in current.membership:
                raise ValueError(f"图片不属于此工作区：{image_id}")
        for group in groups.values():
            if group.representative_image_id and group.representative_image_id not in member_ids(
                doc, group.id
            ):
                raise ValueError("代表图必须属于该组")
            if set(group.evidence_image_ids) - known - set(current.membership):
                raise ValueError("证据图片不属于此工作区")
        if set(doc.locked_image_ids) - set(doc.membership):
            raise ValueError("只能锁定已分组图片")
        if actor == "agent":
            locked_groups = {g.id for g in current.groups if g.locked}
            locked_groups |= {g.id for g in current.groups if g.parent_id in locked_groups}
            for old in current.groups:
                if old.id in locked_groups and groups.get(old.id) != old:
                    raise GroupConflictError(f"Agent 不能覆盖人工锁定的组：{old.name}")
            locked_images = set(current.locked_image_ids) | {
                key for key, target in current.membership.items() if target in locked_groups
            }
            if not set(current.locked_image_ids).issubset(doc.locked_image_ids):
                raise GroupConflictError("Agent 不能解除人工图片锁定")
            for key in set(current.membership) | set(doc.membership):
                if (
                    key in locked_images or doc.membership.get(key) in locked_groups
                ) and current.membership.get(key) != doc.membership.get(key):
                    raise GroupConflictError("Agent 不能改变人工锁定的图片归属")

    def save(
        self, doc: CustomGroups, *, actor: str = "user", operation_id: str | None = None
    ) -> CustomGroups:
        with self.store.lock:
            self.validate(doc, actor=actor)
            saved = doc.model_copy(
                update={
                    "revision": doc.revision + 1,
                    "updated_at": time.time(),
                    "operation_id": operation_id,
                }
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self.path, saved.model_dump_json(indent=2))
            return saved

    def payload(self) -> dict:
        doc = self.load()
        images = self.store.load_index(self.info).images
        by_id = {image.id: image for image in images}
        total_posts = len({post_key(image) for image in images})
        result = doc.model_dump(mode="json")
        result["groups"] = []
        for group in sorted(doc.groups, key=lambda g: (g.order, g.name)):
            ids = member_ids(doc, group.id)
            members = [by_id[key] for key in ids if key in by_id]
            dates = sorted({image.post.date for image in members if image.post and image.post.date})
            count = len({post_key(image) for image in members})
            result["groups"].append(
                {
                    **group.model_dump(mode="json"),
                    "image_ids": [image.id for image in members],
                    "image_count": len(members),
                    "post_count": count,
                    "post_share": count / total_posts if total_posts else 0,
                    "date_from": dates[0] if dates else None,
                    "date_to": dates[-1] if dates else None,
                    "usable_count": sum(not source_problems(image) for image in members),
                    "missing_image_ids": [key for key in ids if key not in by_id],
                }
            )
        result["ungrouped_image_ids"] = [
            image.id for image in images if image.id not in doc.membership
        ]
        return result


def source_problems(image: ImageRecord) -> list[str]:
    problems = []
    if not Path(image.path).is_file():
        problems.append("源图不存在")
    if (
        not image.has_metadata
        or image.seed is None
        or not image.model
        or not all(image.generation_size())
    ):
        problems.append("缺少元数据、模型、原种子或生成尺寸")
    flags = set(image.flags) & {
        "vibe_missing",
        "inpaint",
        "img2img",
        "add_original",
        "director_ref",
        "model_unverified",
    }
    if flags:
        problems.append("原参复现受限：" + ", ".join(sorted(flags)))
    if Path(image.path).is_file():
        stat = Path(image.path).stat()
        if stat.st_size != image.size_bytes or stat.st_mtime_ns != image.mtime_ns:
            problems.append("源图已变化，请重扫工作区")
    return problems


def artifact_path(info: WorkspaceInfo, folder: str, identifier: str) -> Path:
    if not re.fullmatch(r"[\w-]{1,100}", identifier):
        raise ValueError("无效记录 id")
    return Path(info.data_dir) / folder / f"{identifier}.json"
