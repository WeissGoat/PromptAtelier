from __future__ import annotations

import json
import os
import re
from pathlib import Path
from pathlib import PurePosixPath
from uuid import uuid4
from datetime import date, datetime

from .action_resolution import ActionNodeValueResolver
from .catalog import CatalogRepository
from .config import (
    PublishingWorkspaceConfig,
    WorkspacePaths,
    init_workspace,
    load_workspace,
)
from .logging import get_logger
from .models import ExportPlan, ExportSummary
from .importing.models import ImportRunRecord, ImportRunSummary
from .importing.service import ImportWorkflowService
from .problems import ProblemCode, ProblemRepository, ProblemStatus
from .views import (
    ClassificationViewBuilder,
    NeeViewPlaylistExporter,
    ViewExportCoordinator,
    WindowsShortcutExporter,
)
from .tasks.service import TaskWorkflowService
from .plans.executor import SubmissionExecutor
from .plans.models import MonthlyPlan, ScheduleEntry
from .plans.paths import PlanPaths
from .plans.repository import PlanRepository
from .plans.service import ScheduleService


logger = get_logger(__name__)


class PublishingService:
    def initialize(self, root: str | Path) -> dict:
        paths, config, created = init_workspace(root)
        CatalogRepository(paths.catalog, backups_dir=paths.backups)
        return {
            "root": str(paths.root),
            "workspace": str(paths.workspace),
            "config": str(paths.config),
            "catalog": str(paths.catalog),
            "created": created,
            "schema": config.schema_id,
        }

    def create_task(
        self,
        root: str | Path,
        task_id: str,
        *,
        title: str | None = None,
        candidates: str | Path | None = None,
        input_type: str | None = None,
        recursive: bool = False,
    ):
        return TaskWorkflowService().create(
            root,
            task_id,
            title=title,
            candidates=candidates,
            input_type=input_type,
            recursive=recursive,
        )

    def import_task_selection(
        self,
        root: str | Path,
        task_id: str,
        selection_name: str,
        source: str | Path,
        *,
        input_type: str | None = None,
        recursive: bool = False,
        mode: str = "replace",
    ):
        if selection_name not in {"all", "post", "cover"}:
            raise ValueError(f"未知选择集合：{selection_name}")
        if mode not in {"replace", "append"}:
            raise ValueError(f"未知导入模式：{mode}")
        return TaskWorkflowService().import_selection(
            root,
            task_id,
            selection_name,
            source,
            input_type=input_type,
            recursive=recursive,
            mode=mode,
        )

    def task_status(self, root: str | Path, task_id: str) -> dict:
        return TaskWorkflowService().status(root, task_id)

    def build_task(self, root: str | Path, task_id: str):
        return TaskWorkflowService().build(root, task_id)

    def schedule_create(
        self,
        root: str | Path,
        month: str,
        *,
        default_import_id: str | None = None,
    ) -> MonthlyPlan:
        return ScheduleService().create_plan(
            root,
            month,
            default_import_id=default_import_id,
        )

    def schedule_show(self, root: str | Path, month: str) -> MonthlyPlan:
        return ScheduleService().get_plan(root, month)

    def schedule_add_entry(
        self,
        root: str | Path,
        month: str,
        entry: ScheduleEntry,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        return ScheduleService().add_entry(
            root,
            month,
            entry,
            expected_revision=expected_revision,
        )

    def schedule_update_entry(
        self,
        root: str | Path,
        month: str,
        entry: ScheduleEntry,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        return ScheduleService().update_entry(
            root,
            month,
            entry,
            expected_revision=expected_revision,
        )

    def schedule_move_date(
        self,
        root: str | Path,
        month: str,
        entry_id: str,
        target_date: date,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        return ScheduleService().move_entry_date(
            root,
            month,
            entry_id,
            target_date,
            expected_revision=expected_revision,
        )

    def schedule_delete_entry(
        self,
        root: str | Path,
        month: str,
        entry_id: str,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        return ScheduleService().delete_entry(
            root,
            month,
            entry_id,
            expected_revision=expected_revision,
        )

    def schedule_lock(
        self,
        root: str | Path,
        month: str,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        return ScheduleService().lock(
            root,
            month,
            expected_revision=expected_revision,
        )

    def schedule_unlock(
        self,
        root: str | Path,
        month: str,
        *,
        expected_revision: int | None = None,
    ) -> MonthlyPlan:
        return ScheduleService().unlock(
            root,
            month,
            expected_revision=expected_revision,
        )

    def schedule_status(self, root: str | Path, month: str) -> dict:
        paths, _ = load_workspace(root)
        plan = ScheduleService().get_plan(root, month)
        executions = PlanRepository().list_executions(
            PlanPaths.from_workspace(paths, month)
        )
        return {
            "plan": plan.model_dump(mode="json", by_alias=True),
            "executions": [item.model_dump(mode="json") for item in executions],
        }

    def schedule_run_due(
        self,
        root: str | Path,
        *,
        now: datetime | None = None,
    ):
        return SubmissionExecutor().run_due(root, now=now)

    def schedule_build_now(self, root: str | Path, month: str, entry_id: str):
        return SubmissionExecutor().build_now(root, month, entry_id)

    def schedule_retry(self, root: str | Path, month: str, entry_id: str):
        return SubmissionExecutor().retry(root, month, entry_id)

    def import_source(
        self,
        root: str | Path,
        source: str | Path,
        *,
        input_type: str | None = None,
        recursive: bool = False,
        strict: bool = False,
        legacy_tolerant: bool = False,
        retry_failed: bool = False,
    ) -> ImportRunSummary:
        paths, config = load_workspace(root)
        return ImportWorkflowService(paths, config).import_source(
            source,
            input_type=input_type,
            recursive=recursive,
            strict=strict,
            legacy_tolerant=legacy_tolerant,
            retry_failed=retry_failed,
        )

    def resume_import(self, root: str | Path, run_id: str) -> ImportRunSummary:
        paths, config = load_workspace(root)
        return ImportWorkflowService(paths, config).resume(run_id)

    def import_status(self, root: str | Path, run_id: str | None = None) -> ImportRunRecord:
        paths, config = load_workspace(root)
        workflow = ImportWorkflowService(paths, config)
        result = workflow.runs.get_run(run_id) if run_id else workflow.runs.latest_run()
        if result is None:
            raise ValueError("Publishing Catalog 尚无 ImportRun")
        return result

    def list_problems(
        self,
        root: str | Path,
        *,
        status: ProblemStatus | None = "open",
        run_id: str | None = None,
        error_code: ProblemCode | None = None,
    ):
        paths, config = load_workspace(root)
        workflow = ImportWorkflowService(paths, config)
        return workflow.problems.list(status=status, run_id=run_id, error_code=error_code)

    def retry_problems(
        self,
        root: str | Path,
        *,
        run_id: str | None = None,
        error_code: ProblemCode | None = None,
    ) -> ImportRunSummary:
        paths, config = load_workspace(root)
        return ImportWorkflowService(paths, config).retry_problems(
            run_id=run_id,
            error_code=error_code,
        )

    def classify(
        self,
        root: str | Path,
        *,
        import_id: str | None = None,
        hierarchy: list[str] | None = None,
    ) -> tuple[ExportPlan, Path]:
        paths, config = load_workspace(root)
        repository = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        if repository.latest_import_id() is None:
            raise ValueError("Publishing Catalog 尚无可分类的导入记录")
        assets = repository.assets_for_import(import_id)
        classification = config.classification
        action_resolution = classification.action_resolution
        configured_design_root = (
            _config_path(paths.root, action_resolution.design_root)
            if action_resolution.design_root
            else None
        )
        node_value_resolver = ActionNodeValueResolver(
            design_root=configured_design_root,
            action_root_name=action_resolution.action_root_name,
            enabled=action_resolution.enabled,
        )
        plan = ClassificationViewBuilder().build(
            assets,
            hierarchy=hierarchy or classification.hierarchy,
            import_id=import_id,
            missing_value=classification.missing_value,
            skip_missing=classification.skip_missing,
            node_value_resolver=node_value_resolver,
        )
        scope_name = import_id or "catalog"
        plan_path = paths.state / f"export_plan_{scope_name}.json"
        _write_json_atomic(plan_path, plan.model_dump(mode="json", by_alias=True))
        _write_json_atomic(
            paths.state / "latest_export_plan.json",
            plan.model_dump(mode="json", by_alias=True),
        )
        logger.info(
            "Publishing 分类完成 import_id=%s assets=%s views=%s",
            import_id or "catalog",
            len(assets),
            len(plan.views),
        )
        if plan.warnings:
            logger.warning(
                "Publishing action resolution produced warnings=%s",
                len(plan.warnings),
            )
        return plan, plan_path

    def export(
        self,
        root: str | Path,
        *,
        import_id: str | None = None,
        hierarchy: list[str] | None = None,
        exporter_types: list[str] | None = None,
    ) -> tuple[ExportPlan, ExportSummary]:
        paths, config = load_workspace(root)
        plan, _ = self.classify(root, import_id=import_id, hierarchy=hierarchy)
        repository = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        scope_name = _export_scope_name(repository, import_id)
        jobs = self._export_jobs(
            paths,
            config,
            exporter_types,
            scope_name=scope_name,
        )
        if not jobs:
            raise ValueError("没有启用任何 Publishing Exporter")
        summary = ViewExportCoordinator(repository).export(plan, jobs)
        return plan, summary

    def _export_jobs(
        self,
        paths: WorkspacePaths,
        config: PublishingWorkspaceConfig,
        requested: list[str] | None,
        *,
        scope_name: str,
    ) -> list[tuple[object, Path]]:
        enabled = requested or [
            name
            for name, is_enabled in (
                ("neev", config.exporters.neev.enabled),
                ("windows_shortcut", config.exporters.windows_shortcut.enabled),
            )
            if is_enabled
        ]
        jobs: list[tuple[object, Path]] = []
        for name in enabled:
            if name == "neev":
                jobs.append(
                    (
                        NeeViewPlaylistExporter(),
                        _scoped_export_path(
                            _config_path(paths.root, config.exporters.neev.root),
                            scope_name,
                        ),
                    )
                )
            elif name == "windows_shortcut":
                jobs.append(
                    (
                        WindowsShortcutExporter(),
                        _scoped_export_path(
                            _config_path(paths.root, config.exporters.windows_shortcut.root),
                            scope_name,
                        ),
                    )
                )
            else:
                raise ValueError(f"未知 Publishing Exporter：{name}")
        return jobs


def _config_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _scoped_export_path(root: Path, scope_name: str) -> Path:
    return root / scope_name


def _export_scope_name(
    repository: CatalogRepository,
    import_id: str | None,
) -> str:
    if import_id is None:
        return "total"

    sources = repository.import_sources()
    source_ref = next(
        (source_ref for current_id, source_ref in sources if current_id == import_id),
        None,
    )
    if source_ref is None:
        raise ValueError(f"ImportRun 不存在：{import_id}")

    candidate = _safe_scope_name(source_ref)
    collision = any(
        current_id != import_id
        and str(other_ref).casefold() != str(source_ref).casefold()
        and _safe_scope_name(other_ref).casefold() == candidate.casefold()
        for current_id, other_ref in sources
    )
    if collision:
        return f"{candidate}_{import_id[:8]}"
    return candidate


def _safe_scope_name(source_ref: str) -> str:
    normalized = str(source_ref).replace("\\", "/").rstrip("/")
    path = PurePosixPath(normalized)
    name = path.stem if path.suffix.casefold() == ".nvpls" else path.name
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(".")
    if not cleaned:
        return "import"
    if cleaned.casefold() in {"con", "prn", "aux", "nul"}:
        return f"_{cleaned}"
    return cleaned


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
