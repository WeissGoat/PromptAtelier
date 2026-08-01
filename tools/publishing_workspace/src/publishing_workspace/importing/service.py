from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from ..config import PublishingWorkspaceConfig, WorkspacePaths
from ..inputs import InputContext, default_input_registry
from ..logging import get_logger
from ..metadata import ActionGroupManifestEnricher, default_image_node_reader_registry
from ..models import ImportedItem, SelectionSet
from ..problems import ProblemCode, ProblemRepository
from .executor import ImportExecutor, ImportStrictFailure
from .locks import WorkspaceLeaseRepository
from .models import ImportRunSummary
from .planner import ImportPlanner
from .progress import ProgressReporter
from .repository import ImportRunRepository
from ..catalog import CatalogRepository


logger = get_logger(__name__)


class ImportWorkflowService:
    def __init__(self, paths: WorkspacePaths, config: PublishingWorkspaceConfig):
        self.paths = paths
        self.config = config
        self.catalog = CatalogRepository(paths.catalog, backups_dir=paths.backups)
        self.runs = ImportRunRepository(self.catalog)
        self.problems = ProblemRepository(self.catalog)
        self.leases = WorkspaceLeaseRepository(self.catalog)
        self.readers = default_image_node_reader_registry()
        self.enrichers = [ActionGroupManifestEnricher()]

    def import_source(
        self,
        source: str | Path,
        *,
        input_type: str | None = None,
        recursive: bool = False,
        strict: bool = False,
        legacy_tolerant: bool = False,
        retry_failed: bool = False,
    ) -> ImportRunSummary:
        run = self.runs.create_run(
            source_type=input_type or "auto",
            source_ref=str(Path(source).expanduser().resolve()),
            mode="import",
            strict=strict,
        )
        lease = self.leases.acquire(run.import_id, allow_takeover=False)
        reporter = ProgressReporter(logger=logger)
        try:
            selection = default_input_registry().load(
                source,
                input_type=input_type,
                context=InputContext(
                    recursive=recursive,
                    strict=strict,
                    legacy_tolerant=legacy_tolerant,
                    image_extensions=set(self.config.image_extensions),
                ),
            )
            selection = selection.model_copy(update={"id": run.import_id})
            self.runs.persist_selection(run.import_id, selection)
            return self._run_planning_and_execution(
                run.import_id,
                lease=lease,
                reporter=reporter,
                retry_failed=retry_failed,
            )
        except KeyboardInterrupt:
            self.runs.interrupt(run.import_id, reason="keyboard_interrupt")
            raise
        except ImportStrictFailure as exc:
            self.runs.interrupt(run.import_id, reason=str(exc))
            return self._snapshot(run.import_id)
        except Exception as exc:
            self.runs.fail(run.import_id, exc)
            raise
        finally:
            self.leases.release(lease)

    def resume(self, run_id: str) -> ImportRunSummary:
        run = self.runs.get_run(run_id)
        if run.status not in {"created", "scanning", "planned", "running", "interrupted"}:
            raise ValueError(f"ImportRun 当前不能 resume：{run.status}")
        lease = self.leases.acquire(run_id, allow_takeover=True)
        reporter = ProgressReporter(logger=logger)
        try:
            self.runs.reset_processing_to_planned(run_id)
            if run.status == "interrupted":
                self.runs.transition(run_id, status="scanning", pipeline_stage="planning")
            elif run.status == "running":
                # 外部终止进程不会触发 KeyboardInterrupt，租约过期后状态仍可能是 running。
                self.runs.transition(run_id, status="planned", pipeline_stage="execution")
            return self._run_planning_and_execution(
                run_id,
                lease=lease,
                reporter=reporter,
                retry_failed=False,
            )
        except KeyboardInterrupt:
            self.runs.interrupt(run_id, reason="keyboard_interrupt")
            raise
        except ImportStrictFailure as exc:
            self.runs.interrupt(run_id, reason=str(exc))
            return self._snapshot(run_id)
        except Exception as exc:
            self.runs.fail(run_id, exc)
            raise
        finally:
            self.leases.release(lease)

    def retry_problems(
        self,
        *,
        run_id: str | None = None,
        error_code: ProblemCode | None = None,
    ) -> ImportRunSummary:
        selected = self.problems.list(status="open", run_id=run_id, error_code=error_code)
        if not selected:
            raise ValueError("没有匹配的 open problem")
        source_ref = f"retry-problems:{run_id or 'all'}"
        run = self.runs.create_run(
            source_type="retry_problems",
            source_ref=source_ref,
            mode="retry_problems",
            strict=False,
        )
        lease = self.leases.acquire(run.import_id, allow_takeover=False)
        reporter = ProgressReporter(logger=logger)
        try:
            items = [
                ImportedItem(
                    source_path=problem.source_path,
                    resolved_path=(
                        problem.source_path
                        if Path(problem.source_path).is_file()
                        else None
                    ),
                    source_type="retry_problems",
                    source_ref=source_ref,
                    source_order=index,
                    display_name=Path(problem.source_path).name,
                )
                for index, problem in enumerate(selected)
            ]
            self.runs.persist_selection(
                run.import_id,
                SelectionSet(
                    id=run.import_id,
                    source_type="retry_problems",
                    source_ref=source_ref,
                    items=items,
                ),
            )
            summary = self._run_planning_and_execution(
                run.import_id,
                lease=lease,
                reporter=reporter,
                retry_failed=True,
            )
            retry_items = [self.runs.get_item(run.import_id, index) for index in range(len(selected))]
            resolved_ids = [
                problem.problem_id
                for problem, item in zip(selected, retry_items)
                if item.status in {"reused_path", "reused_content", "parsed_new"}
            ]
            with self.catalog.connection() as connection:
                self.problems.resolve_ids(connection, resolved_ids)
            return summary
        except KeyboardInterrupt:
            self.runs.interrupt(run.import_id, reason="keyboard_interrupt")
            raise
        except Exception as exc:
            self.runs.fail(run.import_id, exc)
            raise
        finally:
            self.leases.release(lease)

    def _run_planning_and_execution(
        self,
        run_id: str,
        *,
        lease,
        reporter: ProgressReporter,
        retry_failed: bool,
    ) -> ImportRunSummary:
        planner = ImportPlanner(self.catalog, self.runs, self.problems)
        executor = ImportExecutor(
            catalog=self.catalog,
            runs=self.runs,
            problems=self.problems,
            leases=self.leases,
            readers=self.readers,
            enrichers=self.enrichers,
        )
        current_status = self.runs.get_run(run_id).status
        if current_status in {"created", "interrupted", "scanning"}:
            self.runs.transition(run_id, status="scanning", pipeline_stage="planning")
        while True:
            if self.runs.has_items(run_id, status="pending"):
                planner.plan(run_id, retry_failed=retry_failed, reporter=reporter)
            self.runs.transition(run_id, status="planned", pipeline_stage="execution")
            self.runs.transition(run_id, status="running", pipeline_stage="execution")
            executor.execute(run_id, lease=lease, reporter=reporter)
            if not self.runs.has_unfinished_items(run_id):
                break
        return self._snapshot(run_id, finalize=True)

    def _snapshot(self, run_id: str, *, finalize: bool = False) -> ImportRunSummary:
        summary = self.runs.finalize(run_id) if finalize else self.runs.summary(run_id)
        snapshot_path = self.paths.imports / f"{run_id}.json"
        snapshot = {
            "schema": "publishing-workspace.import-run/v2",
            "run": summary.model_dump(mode="json"),
            "items": self.runs.items_for_snapshot(run_id),
            "problems": self.runs.problems_for_snapshot(run_id),
            "reader_counts": summary.reader_counts,
            "warnings": summary.warnings,
        }
        _write_json_atomic(snapshot_path, snapshot)
        return summary.model_copy(update={"snapshot_path": str(snapshot_path)})


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)
