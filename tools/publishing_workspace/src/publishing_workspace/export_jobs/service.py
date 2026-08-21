from __future__ import annotations

import datetime
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from uuid import uuid4

from ..config import WorkspacePaths, load_workspace
from ..logging import get_logger
from ..models import utc_now_iso
from ..packages.builder import PackageBuilder
from ..packages.models import BuildProgress, BuildResult
from ..submissions.repository import SubmissionRepository
from ..tasks.paths import TaskPaths
from .models import (
    ExportJob,
    ExportOutputNotFoundError,
    ExportOutputOpenError,
)
from .repository import ExportJobRepository

logger = get_logger(__name__)


class ExportJobService:
    """应用级后台导出调度服务，负责在后台单线程队列中执行 PackageBuilder。"""

    def __init__(self, builder: PackageBuilder | None = None) -> None:
        self.builder = builder or PackageBuilder()
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._lock = threading.Lock()
        self._closed = False

    def start(self, root: str | Path, task_id: str) -> ExportJob:
        """启动指定投稿任务的后台导出；若已有排队或运行中的任务，直接复用。"""
        paths, _ = load_workspace(root)
        task_paths = TaskPaths.from_workspace(paths, task_id)
        if not task_paths.task_yaml.is_file():
            raise FileNotFoundError(f"投稿任务不存在：{task_id}")

        with self._lock:
            if self._closed:
                raise RuntimeError("ExportJobService 已关闭，无法接受新任务")

            # 检查是否有正在运行或排队中的任务
            existing_jobs = ExportJobRepository.list_for_task(paths, task_id)
            for job in existing_jobs:
                if job.status in {"queued", "running"}:
                    return job

            now_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            job_id = f"job-{now_str}-{uuid4().hex[:6]}"
            new_job = ExportJob(
                job_id=job_id,
                task_id=task_id,
                status="queued",
                phase="validate",
                processed=0,
                total=0,
                percent=0,
                created_at=utc_now_iso(),
                updated_at=utc_now_iso(),
            )
            ExportJobRepository.save(paths, new_job)
            self._executor.submit(self._run_export, paths, root, job_id, task_id)
            return new_job

    def _run_export(
        self,
        paths: WorkspacePaths,
        root: str | Path,
        job_id: str,
        task_id: str,
    ) -> None:
        """后台 worker 函数：负责执行导出并原子持久化进度。"""
        current_job = ExportJobRepository.load(paths, job_id)
        if current_job is None:
            return

        current_job = current_job.model_copy(
            update={
                "status": "running",
                "phase": "validate",
                "updated_at": utc_now_iso(),
            }
        )
        ExportJobRepository.save(paths, current_job)

        def on_progress(p: BuildProgress) -> None:
            nonlocal current_job
            percent = int((p.processed / p.total) * 100) if p.total > 0 else 0
            current_job = current_job.model_copy(
                update={
                    "phase": p.phase,
                    "processed": p.processed,
                    "total": p.total,
                    "percent": percent,
                    "current_selection": p.current_selection,
                    "current_filename": p.current_filename,
                    "updated_at": utc_now_iso(),
                }
            )
            ExportJobRepository.save(paths, current_job)

        try:
            result = self.builder.build(root, task_id, progress=on_progress)
            task_paths = TaskPaths.from_workspace(paths, task_id)

            current_job = current_job.model_copy(
                update={
                    "status": "completed",
                    "phase": "finalize",
                    "percent": 100,
                    "build_id": result.build_id,
                    "output_dir": str(result.build_root),
                    "updated_at": utc_now_iso(),
                }
            )
            ExportJobRepository.save(paths, current_job)

            # 更新 submission.yaml 的 last_export 摘要
            SubmissionRepository.update_last_export(
                task_paths,
                build_id=result.build_id,
                output_dir=str(result.build_root),
            )
        except Exception as exc:
            logger.exception("导出任务执行失败：%s (%s)", job_id, task_id)
            current_job = current_job.model_copy(
                update={
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "updated_at": utc_now_iso(),
                }
            )
            ExportJobRepository.save(paths, current_job)

    def get(self, root: str | Path, job_id: str) -> ExportJob:
        """获取指定导出任务。"""
        paths, _ = load_workspace(root)
        job = ExportJobRepository.load(paths, job_id)
        if job is None:
            raise FileNotFoundError(f"导出任务不存在：{job_id}")
        return job

    def list_for_task(self, root: str | Path, task_id: str) -> list[ExportJob]:
        """获取指定投稿任务的所有导出记录。"""
        paths, _ = load_workspace(root)
        return ExportJobRepository.list_for_task(paths, task_id)

    def recover_interrupted(self, root: str | Path) -> int:
        """在 Web 启动时恢复未正常完成的孤立任务，将其标记为 interrupted。"""
        paths, _ = load_workspace(root)
        all_jobs = ExportJobRepository.list_all(paths)
        count = 0
        for job in all_jobs:
            if job.status in {"queued", "running"}:
                updated = job.model_copy(
                    update={
                        "status": "interrupted",
                        "error": "Web 服务重启，未完成的导出任务被标记为中断",
                        "updated_at": utc_now_iso(),
                    }
                )
                ExportJobRepository.save(paths, updated)
                count += 1
        return count

    def open_output(self, root: str | Path, job_id: str) -> str:
        """安全打开已完成导出的目录。"""
        paths, _ = load_workspace(root)
        job = self.get(root, job_id)
        if not job.output_dir:
            raise ExportOutputNotFoundError("该任务尚无导出输出目录")

        candidate = Path(job.output_dir).resolve()
        workspace_root = paths.root.resolve()

        try:
            candidate.relative_to(workspace_root)
        except ValueError as exc:
            raise ExportOutputNotFoundError(f"导出目录超出工作区安全范围：{candidate}") from exc

        if not candidate.is_dir():
            raise ExportOutputNotFoundError(f"导出目录不存在：{candidate}")

        try:
            if sys.platform == "win32" and hasattr(os, "startfile"):
                os.startfile(str(candidate))  # type: ignore[attr-defined]
            else:
                raise OSError("当前系统环境不支持直接打开文件管理器")
        except Exception as exc:
            raise ExportOutputOpenError(
                f"无法打开导出目录：{exc}",
                output_dir=str(candidate),
            ) from exc

        return str(candidate)

    def close(self, *, wait: bool = True) -> None:
        """关闭线程池并等待正在运行的任务完成。"""
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=False)
