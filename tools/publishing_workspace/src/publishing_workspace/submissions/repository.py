from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from ..config import WorkspacePaths
from ..logging import get_logger
from ..models import utc_now_iso
from ..plans.models import MonthlyPlan
from ..tasks.paths import TaskPaths
from ..tasks.repository import TaskRepository
from .models import (
    SelectionName,
    Submission,
    SubmissionRevisionConflictError,
    SubmissionScheduleRef,
    SubmissionSummary,
)

logger = get_logger(__name__)

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class SubmissionRepository:
    """Submission 仓库，负责 submission.yaml 的原子读写与历史任务摘要。"""

    @staticmethod
    def load(paths: TaskPaths) -> Submission | None:
        """读取 submission.yaml，文件不存在时返回 None。"""
        if not paths.submission_yaml.is_file():
            return None
        try:
            data = yaml.safe_load(paths.submission_yaml.read_text(encoding="utf-8-sig")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError(f"无法读取投稿配置：{paths.submission_yaml}：{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"投稿配置顶层必须是对象：{paths.submission_yaml}")
        return Submission.model_validate(data)

    @classmethod
    def save(
        cls,
        paths: TaskPaths,
        submission: Submission,
        *,
        expected_revision: int | None = None,
    ) -> Submission:
        """保存 submission.yaml，支持原子写入与 expected_revision 冲突校验。"""
        paths.ensure_layout()
        current = cls.load(paths)
        if expected_revision is not None:
            current_rev = current.revision if current is not None else 1
            if current_rev != expected_revision:
                raise SubmissionRevisionConflictError(
                    f"投稿 revision 已变化：expected={expected_revision} actual={current_rev}"
                )

        next_submission = submission.model_copy(
            update={
                "updated_at": utc_now_iso(),
            }
        )
        _write_yaml_atomic(paths.submission_yaml, next_submission.model_dump(mode="json"))
        return next_submission

    @classmethod
    def update_last_export(
        cls,
        paths: TaskPaths,
        *,
        build_id: str,
        output_dir: str,
    ) -> None:
        """更新 submission.yaml 中的 last_export 摘要。"""
        submission = cls.load(paths)
        if submission is None:
            return
        last_export_data = {
            "build_id": build_id,
            "output_dir": output_dir,
            "exported_at": utc_now_iso(),
        }
        updated = submission.model_copy(update={"last_export": last_export_data})
        cls.save(paths, updated)

    @classmethod
    def list(
        cls,
        paths: WorkspacePaths,
        *,
        plans_dir: Path | None = None,
    ) -> list[SubmissionSummary]:
        """扫描 tasks 目录，返回所有投稿的摘要（包含缺少 submission.yaml 的历史任务）。"""
        if not paths.tasks.is_dir():
            return []

        # 收集所有排期计划中对 task 的引用
        schedule_map = cls._collect_scheduled_entries(plans_dir or paths.plans)

        summaries: list[SubmissionSummary] = []
        for task_dir in sorted(paths.tasks.iterdir(), key=lambda p: p.name):
            if not task_dir.is_dir():
                continue
            task_paths = TaskPaths.from_workspace(paths, task_dir.name)
            if not task_paths.task_yaml.is_file():
                continue

            try:
                summary = cls._summarize_task(task_paths, schedule_map.get(task_dir.name, []))
                if summary is not None:
                    summaries.append(summary)
            except Exception as exc:
                logger.warning("解析任务摘要失败：%s: %s", task_dir.name, exc)

        # 按 updated_at 降序排序
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    @classmethod
    def _summarize_task(
        cls,
        paths: TaskPaths,
        scheduled_entries: list[SubmissionScheduleRef],
    ) -> SubmissionSummary | None:
        submission = cls.load(paths)
        if submission is not None:
            counts: dict[SelectionName, int] = {
                name: len(submission.sets.get(name, []))  # type: ignore[arg-type]
                for name in ("all", "post", "cover")
            }
            return SubmissionSummary(
                submission_id=submission.submission_id,
                task_id=submission.task_id,
                title=submission.title,
                counts=counts,
                updated_at=submission.updated_at,
                scheduled_entries=scheduled_entries,
                last_export=submission.last_export,
                warnings=[],
            )

        # 没有 submission.yaml：兼容旧 task
        try:
            task_config = TaskRepository.load(paths)
        except Exception:
            return None

        counts = {}
        warnings: list[str] = ["缺少 submission.yaml 配置文件"]
        for name in ("all", "post", "cover"):
            selection_dir = paths.selection_dirs[name]
            if selection_dir.is_dir():
                files = [
                    f
                    for f in selection_dir.iterdir()
                    if f.is_file() and f.suffix.casefold() in SUPPORTED_IMAGE_EXTENSIONS
                ]
                counts[name] = len(files)
            else:
                counts[name] = 0

        # 获取 task.yaml 的更新时间
        try:
            mtime = paths.task_yaml.stat().st_mtime
            updated_at = datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc).isoformat()
        except OSError:
            updated_at = utc_now_iso()

        # 检查是否有历史 build
        last_export = None
        if paths.builds_root.is_dir():
            build_dirs = [d for d in paths.builds_root.iterdir() if d.is_dir()]
            if build_dirs:
                build_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
                latest_build = build_dirs[0]
                last_export = {
                    "build_id": latest_build.name,
                    "output_dir": str(latest_build),
                    "exported_at": datetime.datetime.fromtimestamp(
                        latest_build.stat().st_mtime, datetime.timezone.utc
                    ).isoformat(),
                }

        return SubmissionSummary(
            submission_id=task_config.task_id,
            task_id=task_config.task_id,
            title=task_config.title,
            counts=counts,  # type: ignore[arg-type]
            updated_at=updated_at,
            scheduled_entries=scheduled_entries,
            last_export=last_export,
            warnings=warnings,
        )

    @staticmethod
    def _collect_scheduled_entries(
        plans_dir: Path,
    ) -> dict[str, list[SubmissionScheduleRef]]:
        """扫描 plans 目录，统计 task_id 关联的计划引用。"""
        if not plans_dir.is_dir():
            return {}

        result: dict[str, list[SubmissionScheduleRef]] = {}
        for plan_file in sorted(plans_dir.glob("*/plan.yaml")):
            if not plan_file.is_file():
                continue
            try:
                data = yaml.safe_load(plan_file.read_text(encoding="utf-8-sig")) or {}
                if not isinstance(data, dict):
                    continue
                plan = MonthlyPlan.model_validate(data)
                for entry in plan.entries:
                    if entry.content.kind == "task":
                        task_id = str(entry.content.task_id)
                        ref = SubmissionScheduleRef(
                            plan_id=plan.plan_id,
                            entry_id=entry.entry_id,
                            scheduled_at=entry.scheduled_at.isoformat(),
                        )
                        result.setdefault(task_id, []).append(ref)
            except Exception:
                continue
        return result


def _write_yaml_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)
