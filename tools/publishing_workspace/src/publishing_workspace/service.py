from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

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
from .views import (
    ClassificationViewBuilder,
    NeeViewPlaylistExporter,
    ViewExportCoordinator,
    WindowsShortcutExporter,
)


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
        return workflow.runs.get_run(run_id) if run_id else workflow.runs.latest_run()

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
        plan = ClassificationViewBuilder().build(
            assets,
            hierarchy=hierarchy or classification.hierarchy,
            import_id=import_id,
            missing_value=classification.missing_value,
            skip_missing=classification.skip_missing,
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
        jobs = self._export_jobs(paths, config, exporter_types, import_id=import_id)
        if not jobs:
            raise ValueError("没有启用任何 Publishing Exporter")
        summary = ViewExportCoordinator(
            CatalogRepository(paths.catalog, backups_dir=paths.backups)
        ).export(plan, jobs)
        return plan, summary

    def _export_jobs(
        self,
        paths: WorkspacePaths,
        config: PublishingWorkspaceConfig,
        requested: list[str] | None,
        *,
        import_id: str | None,
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
                            import_id,
                        ),
                    )
                )
            elif name == "windows_shortcut":
                jobs.append(
                    (
                        WindowsShortcutExporter(),
                        _scoped_export_path(
                            _config_path(paths.root, config.exporters.windows_shortcut.root),
                            import_id,
                        ),
                    )
                )
            else:
                raise ValueError(f"未知 Publishing Exporter：{name}")
        return jobs


def _config_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _scoped_export_path(root: Path, import_id: str | None) -> Path:
    return root / "_imports" / import_id if import_id else root


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
