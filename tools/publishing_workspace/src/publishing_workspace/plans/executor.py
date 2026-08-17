from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..catalog.repository import CatalogRepository
from ..config import load_workspace
from ..logging import get_logger
from ..packages.builder import PackageBuilder
from ..tasks.service import TaskWorkflowService
from .materializer import InlineTaskMaterializer, MaterializedPlanTask
from .models import ExecutionRecord, InlineContent, MonthlyPlan, ScheduleEntry, TaskContent
from .notifier import ConsoleNotifier, Notifier, NotificationResult, SubmissionEvent
from .paths import PlanPaths
from .repository import PlanRepository


logger = get_logger(__name__)


class SubmissionExecutor:
    def __init__(
        self,
        *,
        notifier: Notifier | None = None,
        repository: PlanRepository | None = None,
        builder: PackageBuilder | None = None,
        materializer: InlineTaskMaterializer | None = None,
    ):
        self.notifier = notifier or ConsoleNotifier()
        self.repository = repository or PlanRepository()
        self.builder = builder or PackageBuilder()
        self.materializer = materializer or InlineTaskMaterializer()

    def run_due(
        self,
        root: str | Path,
        *,
        now: datetime | None = None,
    ) -> list[ExecutionRecord]:
        current_time = now or datetime.now(timezone.utc)
        _require_aware(current_time)
        paths, _ = load_workspace(root)
        records: list[ExecutionRecord] = []
        if not paths.plans.is_dir():
            return records
        for plan_root in sorted(paths.plans.iterdir(), key=lambda item: item.name):
            if not plan_root.is_dir():
                continue
            try:
                plan_paths = PlanPaths.from_workspace(paths, plan_root.name)
                plan = self.repository.load(plan_paths)
            except (OSError, UnicodeError, ValueError) as exc:
                logger.error("到期扫描跳过损坏计划：%s：%s", plan_root, exc)
                continue
            if plan.status != "locked":
                continue
            for entry in sorted(plan.entries, key=lambda item: item.scheduled_at):
                if not entry.execution.build_on_due or entry.scheduled_at > current_time:
                    continue
                execution_id = _due_execution_id(plan, entry)
                if self._has_terminal_or_running_record(plan_paths, execution_id):
                    continue
                records.append(
                    self._execute_entry(
                        root,
                        plan_paths,
                        plan,
                        entry,
                        execution_id=execution_id,
                        reason="due",
                    )
                )
        return records

    def build_now(
        self,
        root: str | Path,
        month: str,
        entry_id: str,
    ) -> ExecutionRecord:
        paths, _ = load_workspace(root)
        plan_paths = PlanPaths.from_workspace(paths, month)
        plan = self.repository.load(plan_paths)
        entry = _find_entry(plan, entry_id)
        return self._execute_entry(
            root,
            plan_paths,
            plan,
            entry,
            execution_id=f"preview-{uuid4().hex[:16]}",
            reason="manual_preview",
        )

    def retry(
        self,
        root: str | Path,
        month: str,
        entry_id: str,
    ) -> ExecutionRecord | None:
        paths, _ = load_workspace(root)
        plan_paths = PlanPaths.from_workspace(paths, month)
        plan = self.repository.load(plan_paths)
        if plan.status != "locked":
            raise ValueError("只有 locked 计划可以重试")
        entry = _find_entry(plan, entry_id)
        previous = self.repository.list_executions(plan_paths, entry_id)
        if not previous or previous[-1].status != "failed":
            return None
        return self._execute_entry(
            root,
            plan_paths,
            plan,
            entry,
            execution_id=f"retry-{uuid4().hex[:16]}",
            reason="retry",
        )

    def _execute_entry(
        self,
        root: str | Path,
        plan_paths: PlanPaths,
        plan: MonthlyPlan,
        entry: ScheduleEntry,
        *,
        execution_id: str,
        reason: str,
    ) -> ExecutionRecord:
        task_id = entry.content.task_id if isinstance(entry.content, TaskContent) else None
        running = ExecutionRecord(
            execution_id=execution_id,
            entry_id=entry.entry_id,
            plan_revision=plan.revision,
            scheduled_at=entry.scheduled_at,
            status="running",
            task_id=task_id,
            reason=reason,
        )
        self.repository.save_execution(plan_paths, running)
        materialized: MaterializedPlanTask | None = None
        try:
            if isinstance(entry.content, TaskContent):
                result = TaskWorkflowService().build(root, entry.content.task_id)
            else:
                paths, _ = load_workspace(root)
                catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
                materialized = self.materializer.materialize(
                    root,
                    plan_id=plan.plan_id,
                    entry=entry,
                    catalog=catalog,
                    execution_id=execution_id,
                )
                result = self.builder.build_paths(
                    materialized.task_paths,
                    output_root=materialized.formal_builds_root,
                )
            completed = running.model_copy(
                update={
                    "status": "completed",
                    "build_id": result.build_id,
                }
            )
        except Exception as exc:
            failed = running.model_copy(
                update={"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            )
            self.repository.save_execution(plan_paths, failed)
            logger.error(
                "投稿构建失败：plan_id=%s entry_id=%s error=%s",
                plan.plan_id,
                entry.entry_id,
                exc,
            )
            return failed
        finally:
            if materialized is not None:
                materialized.cleanup()

        notification = self._notify(plan, entry, completed, result)
        completed = completed.model_copy(
            update={"notification_status": notification.status}
        )
        self.repository.save_execution(plan_paths, completed)
        return completed

    def _notify(self, plan, entry, record, result) -> NotificationResult:
        if not entry.execution.notify_on_complete:
            return NotificationResult(status="disabled")
        event = SubmissionEvent(
            plan_id=plan.plan_id,
            entry_id=entry.entry_id,
            title=entry.title,
            scheduled_at=entry.scheduled_at,
            status="completed",
            build_id=record.build_id,
            task_id=record.task_id,
            output_root=str(result.build_root),
            post_count=result.selection.get("post", 0),
        )
        try:
            return self.notifier.notify(event)
        except Exception as exc:
            logger.error(
                "投稿构建通知失败：plan_id=%s entry_id=%s error=%s",
                plan.plan_id,
                entry.entry_id,
                exc,
            )
            return NotificationResult(status="failed", message=str(exc))

    def _has_terminal_or_running_record(
        self,
        plan_paths: PlanPaths,
        execution_id: str,
    ) -> bool:
        try:
            record = self.repository.load_execution(plan_paths, execution_id)
        except FileNotFoundError:
            return False
        return record.status in {"running", "completed", "failed"}


def _find_entry(plan: MonthlyPlan, entry_id: str) -> ScheduleEntry:
    for entry in plan.entries:
        if entry.entry_id == entry_id:
            return entry
    raise KeyError(f"投稿不存在：{entry_id}")


def _due_execution_id(plan: MonthlyPlan, entry: ScheduleEntry) -> str:
    value = f"{plan.plan_id}|{entry.entry_id}|{plan.revision}|{entry.scheduled_at.isoformat()}"
    return "due-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("执行时间必须包含时区")
