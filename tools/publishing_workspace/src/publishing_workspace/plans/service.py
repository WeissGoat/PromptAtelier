from __future__ import annotations

from datetime import date
from pathlib import Path

from ..catalog.repository import CatalogRepository
from ..config import load_workspace
from ..logging import get_logger
from ..tasks.paths import TaskPaths
from ..tasks.repository import TaskRepository
from ..tasks.scanner import CurrentSelectionScanner
from .models import InlineContent, MonthlyPlan, ScheduleEntry, TaskContent
from .paths import PlanPaths
from .repository import PlanRepository, PlanRevisionConflictError


logger = get_logger(__name__)


class PlanLockedError(RuntimeError):
    """已锁定计划不能直接编辑。"""


class PlanValidationError(ValueError):
    """计划无法锁定或执行前置校验未通过。"""


class ScheduleService:
    def __init__(self, repository: PlanRepository | None = None):
        self.repository = repository or PlanRepository()

    def create_plan(
        self,
        root: str | Path,
        month: str,
        *,
        default_import_id: str | None = None,
    ) -> MonthlyPlan:
        paths, _ = load_workspace(root)
        return self.repository.create(
            PlanPaths.from_workspace(paths, month),
            default_import_id=default_import_id,
        )

    def get_plan(self, root: str | Path, month: str) -> MonthlyPlan:
        paths, _ = load_workspace(root)
        return self.repository.load(PlanPaths.from_workspace(paths, month))

    def add_entry(
        self,
        root: str | Path,
        month: str,
        entry: ScheduleEntry,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        paths, _ = load_workspace(root)
        plan_paths = PlanPaths.from_workspace(paths, month)
        plan = self.repository.load(plan_paths)
        self._ensure_editable(plan)
        self._ensure_revision(plan, expected_revision)
        if any(item.entry_id == entry.entry_id for item in plan.entries):
            raise ValueError(f"entry_id 已存在：{entry.entry_id}")
        updated = plan.model_copy(update={"entries": [*plan.entries, entry]})
        self._warn_schedule_conflicts(updated)
        return self.repository.save(
            plan_paths,
            updated,
            expected_revision=expected_revision,
        )

    def update_entry(
        self,
        root: str | Path,
        month: str,
        entry: ScheduleEntry,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        paths, _ = load_workspace(root)
        plan_paths = PlanPaths.from_workspace(paths, month)
        plan = self.repository.load(plan_paths)
        self._ensure_editable(plan)
        self._ensure_revision(plan, expected_revision)
        if not any(item.entry_id == entry.entry_id for item in plan.entries):
            raise KeyError(f"投稿不存在：{entry.entry_id}")
        updated = plan.model_copy(
            update={
                "entries": [
                    entry if item.entry_id == entry.entry_id else item
                    for item in plan.entries
                ]
            }
        )
        self._warn_schedule_conflicts(updated)
        return self.repository.save(
            plan_paths,
            updated,
            expected_revision=expected_revision,
        )

    def move_entry_date(
        self,
        root: str | Path,
        month: str,
        entry_id: str,
        target_date: date,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        paths, _ = load_workspace(root)
        plan_paths = PlanPaths.from_workspace(paths, month)
        plan = self.repository.load(plan_paths)
        self._ensure_editable(plan)
        self._ensure_revision(plan, expected_revision)
        self._ensure_target_date(plan, target_date)
        if not any(item.entry_id == entry_id for item in plan.entries):
            raise KeyError(f"投稿不存在：{entry_id}")
        updated = plan.model_copy(
            update={
                "entries": [
                    item.model_copy(
                        update={
                            "scheduled_at": item.scheduled_at.replace(
                                year=target_date.year,
                                month=target_date.month,
                                day=target_date.day,
                            )
                        }
                    )
                    if item.entry_id == entry_id
                    else item
                    for item in plan.entries
                ]
            }
        )
        self._warn_schedule_conflicts(updated)
        return self.repository.save(
            plan_paths,
            updated,
            expected_revision=expected_revision,
        )

    def delete_entry(
        self,
        root: str | Path,
        month: str,
        entry_id: str,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        paths, _ = load_workspace(root)
        plan_paths = PlanPaths.from_workspace(paths, month)
        plan = self.repository.load(plan_paths)
        self._ensure_editable(plan)
        self._ensure_revision(plan, expected_revision)
        entries = [item for item in plan.entries if item.entry_id != entry_id]
        if len(entries) == len(plan.entries):
            raise KeyError(f"投稿不存在：{entry_id}")
        return self.repository.save(
            plan_paths,
            plan.model_copy(update={"entries": entries}),
            expected_revision=expected_revision,
        )

    def lock(
        self,
        root: str | Path,
        month: str,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        paths, config = load_workspace(root)
        plan_paths = PlanPaths.from_workspace(paths, month)
        plan = self.repository.load(plan_paths)
        self._ensure_editable(plan)
        self._ensure_revision(plan, expected_revision)
        self._validate_lock_references(paths, config.image_extensions, plan)
        self._warn_schedule_conflicts(plan)
        return self.repository.save(
            plan_paths,
            plan.model_copy(update={"status": "locked"}),
            expected_revision=expected_revision,
        )

    def unlock(
        self,
        root: str | Path,
        month: str,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        paths, _ = load_workspace(root)
        plan_paths = PlanPaths.from_workspace(paths, month)
        plan = self.repository.load(plan_paths)
        self._ensure_revision(plan, expected_revision)
        return self.repository.save(
            plan_paths,
            plan.model_copy(update={"status": "draft"}),
            expected_revision=expected_revision,
        )

    @staticmethod
    def _ensure_editable(plan: MonthlyPlan) -> None:
        if plan.status == "locked":
            raise PlanLockedError(f"月度计划已锁定：{plan.plan_id}")

    @staticmethod
    def _ensure_revision(plan: MonthlyPlan, expected_revision: int | None) -> None:
        if expected_revision is not None and plan.revision != expected_revision:
            raise PlanRevisionConflictError(
                f"月度计划 revision 已变化：expected={expected_revision} actual={plan.revision}"
            )

    @staticmethod
    def _ensure_target_date(plan: MonthlyPlan, target_date: date) -> None:
        if target_date.strftime("%Y-%m") != plan.month:
            raise PlanValidationError(
                f"拖拽目标日期不属于计划月份：{target_date} -> {plan.month}"
            )

    @staticmethod
    def _warn_schedule_conflicts(plan: MonthlyPlan) -> None:
        seen: set[str] = set()
        for entry in plan.entries:
            key = entry.scheduled_at.isoformat()
            if key in seen:
                logger.warning(
                    "同一时间存在多条投稿：plan_id=%s scheduled_at=%s",
                    plan.plan_id,
                    key,
                )
            seen.add(key)

    def _validate_lock_references(
        self,
        paths,
        image_extensions: list[str],
        plan: MonthlyPlan,
    ) -> None:
        if not plan.entries:
            raise PlanValidationError("月度计划至少需要一条投稿")
        catalog: CatalogRepository | None = None
        for entry in plan.entries:
            if isinstance(entry.content, TaskContent):
                self._validate_task_entry(paths, image_extensions, entry)
                continue
            if catalog is None:
                catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
            self._validate_inline_entry(catalog, entry)

    @staticmethod
    def _validate_task_entry(paths, image_extensions: list[str], entry: ScheduleEntry) -> None:
        task_paths = TaskPaths.from_workspace(paths, entry.content.task_id)
        TaskRepository.load(task_paths)
        selections = CurrentSelectionScanner().scan(
            task_paths,
            {extension.casefold() for extension in image_extensions},
        )
        if not selections["post"]:
            raise PlanValidationError(
                f"投稿 entry 的 task 没有 post 图片：{entry.entry_id} -> {entry.content.task_id}"
            )
        if not selections["all"]:
            logger.warning("投稿 task 的 all 集合为空：entry_id=%s", entry.entry_id)
        if not selections["cover"]:
            logger.warning("投稿 task 的 cover 集合为空：entry_id=%s", entry.entry_id)

    @staticmethod
    def _validate_inline_entry(catalog: CatalogRepository, entry: ScheduleEntry) -> None:
        content = entry.content
        assert isinstance(content, InlineContent)
        if not content.sets["post"]:
            raise PlanValidationError(f"散图投稿没有 post 图片：{entry.entry_id}")
        available = {
            asset.asset_id
            for asset in catalog.assets_for_import(content.source_import_id)
        }
        requested = {
            asset_id
            for values in content.sets.values()
            for asset_id in values
        }
        missing = sorted(requested - available)
        if missing:
            raise PlanValidationError(
                f"散图投稿引用了不存在的 asset_id：{entry.entry_id} -> {missing}"
            )
        if not content.sets["all"]:
            logger.warning("散图投稿的 all 集合为空：entry_id=%s", entry.entry_id)
        if not content.sets["cover"]:
            logger.warning("散图投稿的 cover 集合为空：entry_id=%s", entry.entry_id)
        if not set(content.sets["post"]).issubset(content.sets["all"]):
            logger.warning("post 不是 all 的子集：entry_id=%s", entry.entry_id)
        if not set(content.sets["cover"]).issubset(content.sets["post"]):
            logger.warning("cover 不是 post 的子集：entry_id=%s", entry.entry_id)
