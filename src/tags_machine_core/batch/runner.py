from __future__ import annotations

import time
import json
from pathlib import Path
from typing import Any

from tags_machine_core.config import AppConfig

from .archive import BatchArchive
from .executor import BatchExecutionResult, BatchExecutor
from .manifest import (
    append_manifest_entry,
    manifest_entry_for_task,
    task_already_succeeded,
    write_initial_manifest,
)
from .models import ArchiveConfig, BatchTask, ReportConfig, RunConfig
from .report import write_report


class BatchRunner:
    def __init__(
        self,
        *,
        executor: BatchExecutor | None = None,
        archive: BatchArchive | None = None,
    ):
        self.executor = executor or BatchExecutor()
        self.archive = archive or BatchArchive()

    def run_tasks(
        self,
        *,
        run_dir: str | Path,
        tasks: list[BatchTask],
        config: AppConfig,
        run_config: RunConfig | None = None,
        archive_config: ArchiveConfig | None = None,
        report_config: ReportConfig | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        run_config = run_config or RunConfig()
        archive_config = archive_config or ArchiveConfig()
        report_config = report_config or ReportConfig()
        self.archive = BatchArchive(archive_config)
        effective_config = _config_with_timeout(config, run_config.retry.timeout_seconds)

        root = Path(run_dir)
        root.mkdir(parents=True, exist_ok=True)
        if not (run_config.resume and (root / "manifest.jsonl").exists()):
            write_initial_manifest(root, tasks)

        entries: list[dict[str, Any]] = []
        image_budget = run_config.max_images
        selected = tasks[:limit] if limit is not None else tasks
        for task in selected:
            if image_budget is not None and image_budget <= 0:
                break
            run_task = _task_with_image_budget(task, image_budget)
            if run_config.resume and task_already_succeeded(task):
                entry = self._record_skipped(run_dir=root, task=task)
                entries.append(entry)
                continue

            self.archive.write_task(run_task)
            result = self._execute_with_retry(
                root=root,
                task=run_task,
                config=effective_config,
                run_config=run_config,
                archive_config=archive_config,
            )
            entries.append(result)
            if result["status"] == "succeeded" and image_budget is not None:
                image_budget -= max(1, len(result.get("image_paths") or []))
            if result["status"] == "failed" and run_config.stop_on_error:
                break

        report = write_report(
            root,
            entries,
            markdown=report_config.markdown,
            json_report=report_config.json_report,
        )
        return {"run_dir": str(root), "counts": report["counts"], "entries": entries}

    def _execute_with_retry(
        self,
        *,
        root: Path,
        task: BatchTask,
        config: AppConfig,
        run_config: RunConfig,
        archive_config: ArchiveConfig,
    ) -> dict[str, Any]:
        max_attempts = run_config.retry.max_attempts
        last_error: str | None = None
        retry_records: list[dict[str, Any]] = []
        for attempt in range(1, max_attempts + 1):
            self.archive.write_status(task, status="running", attempt=attempt)
            append_manifest_entry(
                root,
                manifest_entry_for_task(
                    run_dir=root,
                    task=task,
                    status="running",
                    attempt=attempt,
                ),
            )
            try:
                output_dir = (
                    Path(task.output.task_dir) / "images"
                    if archive_config.copy_images
                    else task.render.output_dir
                )
                result = self.executor.execute(task, config=config, output_dir=output_dir)
                return self._handle_execution_result(
                    root=root,
                    task=task,
                    attempt=attempt,
                    result=result,
                )
            except Exception as exc:
                last_error = str(exc)
                retry_record = {
                    "attempt": attempt,
                    "error": last_error,
                    "retryable": attempt < max_attempts and _retryable(exc, run_config.retry.retry_on),
                }
                if attempt >= max_attempts or not _retryable(exc, run_config.retry.retry_on):
                    retry_records.append(retry_record)
                    entry = self._record(
                        run_dir=root,
                        task=task,
                        status="failed",
                        attempt=attempt,
                        image_paths=[],
                        error=last_error,
                    )
                    entry["retry_records"] = retry_records
                    return entry
                delay = _retry_delay(run_config.retry.backoff_seconds, attempt)
                retry_record["delay_seconds"] = delay
                retry_records.append(retry_record)
                self.archive.write_status(
                    task,
                    status="running",
                    attempt=attempt,
                    warning=f"retry scheduled after error: {last_error}",
                )
                time.sleep(delay)
        return self._record(
            run_dir=root,
            task=task,
            status="failed",
            attempt=max_attempts,
            image_paths=[],
            error=last_error or "unknown error",
        )

    def _handle_execution_result(
        self,
        *,
        root: Path,
        task: BatchTask,
        attempt: int,
        result: BatchExecutionResult,
    ) -> dict[str, Any]:
        if result.status == "requires_agent":
            self.archive.write_agent_task(run_dir=root, task=task, value=result.agent_task)
            return self._record(
                run_dir=root,
                task=task,
                status="requires_agent",
                attempt=attempt,
                image_paths=[],
                error=None,
            )
        if result.status != "succeeded":
            return self._record(
                run_dir=root,
                task=task,
                status="failed",
                attempt=attempt,
                image_paths=[],
                error=result.error or f"unexpected status: {result.status}",
            )
        if result.prompt_bundle is None or result.render_request is None or result.generation_result is None:
            return self._record(
                run_dir=root,
                task=task,
                status="failed",
                attempt=attempt,
                image_paths=[],
                error="executor returned incomplete success artifacts",
            )
        archived_generation = self.archive.archive_success(
            task=task,
            prompt_bundle=result.prompt_bundle,
            render_request=result.render_request,
            generation_result=result.generation_result,
        )
        entry = self._record(
            run_dir=root,
            task=task,
            status="succeeded",
            attempt=attempt,
            image_paths=[str(image.path) for image in archived_generation.images],
            error=None,
        )
        entry["prompt_preview"] = result.render_request.prompt[:300]
        entry["png_params_summary"] = {
            "image_count": len(archived_generation.png_info.get("images", [])),
            "has_png_info": bool(archived_generation.png_info),
        }
        return entry

    def _record(
        self,
        *,
        run_dir: Path,
        task: BatchTask,
        status: str,
        attempt: int,
        image_paths: list[str],
        error: str | None,
    ) -> dict[str, Any]:
        self.archive.write_status(
            task,
            status=status,  # type: ignore[arg-type]
            attempt=attempt,
            image_paths=image_paths,
            error=error,
        )
        append_manifest_entry(
            run_dir,
            manifest_entry_for_task(
                run_dir=run_dir,
                task=task,
                status=status,  # type: ignore[arg-type]
                attempt=attempt,
                image_paths=image_paths,
                error=error,
            ),
        )
        return {
            "task_id": task.id,
            "status": status,
            "attempt": attempt,
            "task_dir": task.output.task_dir,
            "image_paths": image_paths,
            "error": error,
        }

    def _record_skipped(self, *, run_dir: Path, task: BatchTask) -> dict[str, Any]:
        image_paths: list[str] = []
        status_path = Path(task.output.task_dir) / "status.json"
        if status_path.exists():
            try:
                data = json.loads(status_path.read_text(encoding="utf-8"))
                image_paths = [str(item) for item in data.get("image_paths") or []]
            except json.JSONDecodeError:
                image_paths = []
        return {
            "task_id": task.id,
            "status": "skipped",
            "attempt": 0,
            "task_dir": task.output.task_dir,
            "image_paths": image_paths,
            "error": None,
        }


def _task_with_image_budget(task: BatchTask, image_budget: int | None) -> BatchTask:
    if image_budget is None or image_budget >= task.render.nt:
        return task
    return task.model_copy(
        deep=True,
        update={"render": task.render.model_copy(update={"nt": max(1, image_budget)})},
    )


def _retryable(exc: Exception, retry_on: list[str]) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(str(item).lower() in text for item in retry_on)


def _retry_delay(values: list[float], attempt: int) -> float:
    if not values:
        return 0
    return values[min(attempt - 1, len(values) - 1)]


def _config_with_timeout(config: AppConfig, timeout_seconds: float | None) -> AppConfig:
    if timeout_seconds is None:
        return config
    timeout = max(1, int(timeout_seconds))
    return config.model_copy(
        deep=True,
        update={
            "novelai": config.novelai.model_copy(update={"timeout": timeout}),
            "comfyui": config.comfyui.model_copy(update={"timeout": timeout}),
            "sd": config.sd.model_copy(update={"timeout": timeout}),
        },
    )
