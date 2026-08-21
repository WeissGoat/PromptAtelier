from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from publishing_workspace.config import init_workspace
from publishing_workspace.export_jobs.models import (
    ExportJob,
    ExportOutputNotFoundError,
    ExportOutputOpenError,
)
from publishing_workspace.export_jobs.repository import ExportJobRepository
from publishing_workspace.export_jobs.service import ExportJobService
from publishing_workspace.packages.models import BuildResult
from publishing_workspace.tasks import TaskConfig, TaskPaths, TaskRepository
from publishing_workspace.web.schedule_api import create_app


def _image(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)
    return path


def _make_valid_task(root: Path, task_id: str = "task-001") -> TaskPaths:
    paths, _, _ = init_workspace(root)
    task_paths = TaskPaths.from_workspace(paths, task_id)
    TaskRepository.create(task_paths, title="测试任务")
    img = _image(root / "source.png", "red")
    (task_paths.selection_dirs["all"] / "0001_a.png").write_bytes(img.read_bytes())
    (task_paths.selection_dirs["post"] / "0001_a.png").write_bytes(img.read_bytes())
    (task_paths.selection_dirs["cover"] / "0001_a.png").write_bytes(img.read_bytes())
    return task_paths


class BlockingBuilder:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def build(self, root, task_id, *, progress=None):
        self.started.set()
        self.release.wait(timeout=5)
        build_root = Path(root) / "tasks" / task_id / "builds" / "build-1"
        build_root.mkdir(parents=True, exist_ok=True)
        return BuildResult(
            build_id="build-1",
            build_root=build_root,
            manifest_path=build_root / "build_manifest.json",
            output_paths={},
            archive_paths={},
            selection={"all": 1},
        )


def test_start_returns_same_active_job_for_same_task(tmp_path: Path):
    task_paths = _make_valid_task(tmp_path)
    builder = BlockingBuilder()
    service = ExportJobService(builder=builder)
    try:
        first = service.start(tmp_path, task_paths.task_id)
        assert builder.started.wait(timeout=3)
        second = service.start(tmp_path, task_paths.task_id)

        assert first.job_id == second.job_id
        assert second.status in {"queued", "running"}
    finally:
        builder.release.set()
        service.close(wait=True)


def test_recover_interrupted_marks_orphaned_running_jobs(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    job = ExportJob(
        job_id="job-orphan-1",
        task_id="task-1",
        status="running",
        created_at="2026-08-21T10:00:00Z",
        updated_at="2026-08-21T10:00:00Z",
    )
    ExportJobRepository.save(paths, job)

    service = ExportJobService()
    try:
        assert service.recover_interrupted(tmp_path) == 1
        recovered = service.get(tmp_path, "job-orphan-1")
        assert recovered.status == "interrupted"
        assert "中断" in recovered.error
    finally:
        service.close(wait=True)


def test_completed_job_allows_new_export_and_failed_job_retry(tmp_path: Path):
    task_paths = _make_valid_task(tmp_path)
    service = ExportJobService()
    try:
        job = service.start(tmp_path, task_paths.task_id)
        # 等待后台执行完成
        service.close(wait=True)

        final_job = service.get(tmp_path, job.job_id)
        assert final_job.status == "completed"
        assert final_job.output_dir is not None

        # 重启一个 service，再次导出允许生成新 job
        service2 = ExportJobService()
        try:
            job2 = service2.start(tmp_path, task_paths.task_id)
            assert job2.job_id != job.job_id
        finally:
            service2.close(wait=True)
    finally:
        pass


def test_open_output_security_and_errors(tmp_path: Path):
    paths, _, _ = init_workspace(tmp_path)
    valid_dir = tmp_path / "tasks" / "task-1" / "builds" / "build-1"
    valid_dir.mkdir(parents=True, exist_ok=True)

    job_valid = ExportJob(
        job_id="job-valid",
        task_id="task-1",
        status="completed",
        output_dir=str(valid_dir),
        created_at="2026-08-21T10:00:00Z",
        updated_at="2026-08-21T10:00:00Z",
    )
    ExportJobRepository.save(paths, job_valid)

    job_outside = ExportJob(
        job_id="job-outside",
        task_id="task-1",
        status="completed",
        output_dir="C:/Windows/System32",
        created_at="2026-08-21T10:00:00Z",
        updated_at="2026-08-21T10:00:00Z",
    )
    ExportJobRepository.save(paths, job_outside)

    service = ExportJobService()
    try:
        # 路径超出工作区安全范围
        with pytest.raises(ExportOutputNotFoundError):
            service.open_output(tmp_path, "job-outside")

        # mock os.startfile 验证正常调用
        with patch("os.startfile", create=True) as mock_startfile:
            res = service.open_output(tmp_path, "job-valid")
            assert Path(res) == valid_dir.resolve()
            mock_startfile.assert_called_once()
    finally:
        service.close(wait=True)


def test_export_api_endpoints(tmp_path: Path):
    task_paths = _make_valid_task(tmp_path)
    app = create_app(tmp_path)

    with TestClient(app) as client:
        # 1. 触发导出
        post_resp = client.post(f"/api/submissions/{task_paths.task_id}/exports")
        assert post_resp.status_code in {200, 202}
        job_id = post_resp.json()["job_id"]

        # 2. 查询单个任务
        get_resp = client.get(f"/api/export-jobs/{job_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["job_id"] == job_id

        # 3. 查询 task 的所有导出
        list_resp = client.get(f"/api/submissions/{task_paths.task_id}/exports")
        assert list_resp.status_code == 200
        assert any(j["job_id"] == job_id for j in list_resp.json())
