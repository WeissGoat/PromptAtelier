from __future__ import annotations

import json
from pathlib import Path

import pytest

from publishing_workspace.config import WorkspacePaths
from publishing_workspace.tasks import SelectionImportHistory, TaskConfig, TaskPaths, TaskRepository


def test_task_paths_create_all_selection_directories(tmp_path: Path):
    paths = TaskPaths.from_workspace(
        WorkspacePaths.from_root(tmp_path / "publish"),
        "homura_foot",
    )

    paths.ensure_layout()

    assert paths.task_root == tmp_path / "publish" / "tasks" / "homura_foot"
    assert paths.task_yaml.is_file() is False
    assert paths.history_dir.is_dir()
    assert set(paths.selection_dirs) == {"all", "post", "cover"}


def test_task_id_cannot_escape_tasks_root(tmp_path: Path):
    with pytest.raises(ValueError, match="task_id"):
        TaskPaths.from_workspace(
            WorkspacePaths.from_root(tmp_path / "publish"),
            "../outside",
        )


def test_task_repository_round_trips_config_and_history(tmp_path: Path):
    paths = TaskPaths.from_workspace(
        WorkspacePaths.from_root(tmp_path / "publish"),
        "task-001",
    )
    created = TaskRepository.create(paths, title="投稿任务")

    assert TaskRepository.load(paths) == created

    history = SelectionImportHistory(
        history_id="history-001",
        selection="all",
        mode="replace",
        source_type="directory",
        source_ref="F:/source",
        materialized_files=["0001_a.png"],
    )
    history_path = TaskRepository.record_history(paths, history)

    assert history_path.is_file()
    assert json.loads(history_path.read_text(encoding="utf-8"))["selection"] == "all"
