from dataclasses import dataclass, field
import logging
from pathlib import Path

from .config import TaskToolsConfig
from .logging import configure_task_tool_file_logging
from .models import TaskContextSet
from .registry import OperationRegistry


@dataclass(frozen=True, slots=True)
class OperationResult:
    operation_id: str
    affected_paths: list[Path] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True, slots=True)
class OperationAvailability:
    enabled: bool
    reason: str = ""


class OperationUnavailableError(RuntimeError):
    """操作存在但不适用于当前任务上下文。"""


class TaskToolRunner:
    def __init__(
        self,
        *,
        registry: OperationRegistry,
        config: TaskToolsConfig,
        log_dir: Path | None = None,
        log_level: str = "error",
    ):
        self.registry = registry
        self.config = config
        self.logger: logging.Logger = configure_task_tool_file_logging(log_dir, log_level)

    def availability(
        self,
        operation_id: str,
        contexts: TaskContextSet,
    ) -> OperationAvailability:
        try:
            spec = self.registry.get(operation_id)
        except KeyError:
            return OperationAvailability(False, f"未知操作：{operation_id}")
        override = self.config.operations[operation_id]
        if not override.enabled:
            return OperationAvailability(False, "操作已禁用")
        if spec.handler is None:
            return OperationAvailability(False, "操作尚未绑定处理器")
        resources = contexts.resources_for(spec.target_role)
        if not resources:
            return OperationAvailability(False, f"未找到 {spec.target_role} 关联资源")
        if not any(resource.exists for resource in resources):
            return OperationAvailability(False, f"{spec.target_role} 目录不存在")
        if not spec.supports_multiple_tasks and len(contexts.tasks) > 1:
            return OperationAvailability(False, "该操作不支持多个任务")
        if (
            not spec.supports_multiple_resources
            and len(contexts.existing_paths(spec.target_role)) > 1
        ):
            return OperationAvailability(False, "该操作不支持多个关联资源")
        return OperationAvailability(True)

    def run(self, operation_id: str, contexts: TaskContextSet) -> OperationResult:
        self.logger.info("开始执行任务工具操作：%s", operation_id)
        try:
            availability = self.availability(operation_id, contexts)
            if not availability.enabled:
                raise OperationUnavailableError(availability.reason)
            handler = self.registry.get(operation_id).handler
            if handler is None:
                raise OperationUnavailableError("操作尚未绑定处理器")
            result = handler(contexts)
        except Exception:
            self.logger.exception("任务工具操作执行失败：%s", operation_id)
            raise
        self.logger.info("任务工具操作执行成功：%s", operation_id)
        return result
