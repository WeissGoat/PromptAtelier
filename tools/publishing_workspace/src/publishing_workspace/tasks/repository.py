from __future__ import annotations

import json
import os
import re
from pathlib import Path
from uuid import uuid4

import yaml

from .models import SelectionImportHistory, TaskConfig
from .paths import TaskPaths


class TaskRepository:
    @classmethod
    def create(cls, paths: TaskPaths, *, title: str | None = None) -> TaskConfig:
        paths.ensure_layout()
        if paths.task_yaml.exists():
            raise FileExistsError(f"投稿任务已存在：{paths.task_id}")
        config = TaskConfig(
            task_id=paths.task_id,
            title=(title or paths.task_id).strip(),
        )
        cls.save(paths, config)
        return config

    @staticmethod
    def load(paths: TaskPaths) -> TaskConfig:
        if not paths.task_yaml.is_file():
            raise FileNotFoundError(f"投稿任务不存在：{paths.task_yaml}")
        try:
            data = yaml.safe_load(paths.task_yaml.read_text(encoding="utf-8-sig")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError(f"无法读取投稿任务配置：{paths.task_yaml}：{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"投稿任务配置顶层必须是对象：{paths.task_yaml}")
        return TaskConfig.model_validate(data)

    @staticmethod
    def save(paths: TaskPaths, config: TaskConfig) -> None:
        if config.task_id != paths.task_id:
            raise ValueError("TaskConfig.task_id 与任务路径不一致")
        paths.ensure_layout()
        _write_yaml_atomic(paths.task_yaml, config.model_dump(mode="json"))

    @staticmethod
    def record_history(paths: TaskPaths, record: SelectionImportHistory) -> Path:
        paths.ensure_layout()
        timestamp = re.sub(r"[^0-9A-Za-z_-]", "", record.imported_at)
        filename = f"{timestamp}-{record.selection}-{record.history_id}.json"
        target = paths.history_dir / filename
        _write_json_atomic(target, record.model_dump(mode="json"))
        return target


def _write_yaml_atomic(path: Path, data: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_json_atomic(path: Path, data: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
