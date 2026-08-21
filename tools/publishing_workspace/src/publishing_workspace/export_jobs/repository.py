from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from ..config import WorkspacePaths
from ..logging import get_logger
from .models import ExportJob

logger = get_logger(__name__)


class ExportJobRepository:
    """导出任务持久化仓库，基于 JSON 文件原子读写。"""

    @staticmethod
    def _jobs_dir(paths: WorkspacePaths) -> Path:
        directory = paths.state / "export_jobs"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @classmethod
    def save(cls, paths: WorkspacePaths, job: ExportJob) -> None:
        """原子保存导出任务状态。"""
        jobs_dir = cls._jobs_dir(paths)
        target_path = jobs_dir / f"{job.job_id}.json"
        _write_json_atomic(target_path, job.model_dump(mode="json", by_alias=True))

    @classmethod
    def load(cls, paths: WorkspacePaths, job_id: str) -> ExportJob | None:
        """加载指定 ID 的导出任务；不存在时返回 None。"""
        jobs_dir = cls._jobs_dir(paths)
        target_path = jobs_dir / f"{job_id}.json"
        if not target_path.is_file():
            return None
        try:
            data = json.loads(target_path.read_text(encoding="utf-8"))
            return ExportJob.model_validate(data)
        except Exception as exc:
            logger.warning("读取导出任务失败：%s: %s", target_path, exc)
            return None

    @classmethod
    def list_all(cls, paths: WorkspacePaths) -> list[ExportJob]:
        """列出所有导出任务，按 created_at 降序排列。"""
        jobs_dir = cls._jobs_dir(paths)
        if not jobs_dir.is_dir():
            return []

        jobs: list[ExportJob] = []
        for file_path in sorted(jobs_dir.glob("*.json"), key=lambda p: p.name, reverse=True):
            if not file_path.is_file():
                continue
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                jobs.append(ExportJob.model_validate(data))
            except Exception as exc:
                logger.warning("跳过损坏的导出任务状态：%s: %s", file_path, exc)

        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    @classmethod
    def list_for_task(cls, paths: WorkspacePaths, task_id: str) -> list[ExportJob]:
        """获取指定 task 的所有导出任务，按 created_at 降序排列。"""
        all_jobs = cls.list_all(paths)
        return [j for j in all_jobs if j.task_id == task_id]


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
