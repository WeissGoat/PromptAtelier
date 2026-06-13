from __future__ import annotations

import time
import json
from pathlib import Path
from typing import Any

from tags_machine_core.config import AppConfig
from tags_machine_core.logging_config import get_logger

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


logger = get_logger(__name__)


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
        logger.info(
            "batch run started run_dir=%s task_count=%s limit=%s resume=%s max_images=%s",
            root,
            len(tasks),
            limit,
            run_config.resume,
            run_config.max_images,
        )

        entries: list[dict[str, Any]] = []
        image_budget = run_config.max_images
        selected = tasks[:limit] if limit is not None else tasks
        total_selected = len(selected)
        for position, planned_task in enumerate(selected, start=1):
            if image_budget is not None and image_budget <= 0:
                break
            task = _resume_task_snapshot(planned_task) if run_config.resume else planned_task
            if run_config.resume and task_already_succeeded(task):
                entry = self._record_skipped(run_dir=root, task=task)
                entries.append(entry)
                logger.info("batch task skipped task_id=%s source=%s", task.id, _source_log(task))
                continue

            run_task = _task_with_image_budget(task, image_budget)
            self.archive.write_task(run_task)
            logger.info(
                "batch task started index=%s/%s task_id=%s composer=%s source=%s resolution=%s nt=%s seed=%s",
                position,
                total_selected,
                run_task.id,
                run_task.composer,
                _source_log(run_task),
                run_task.render.resolution,
                run_task.render.nt,
                run_task.render.seed,
            )
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
                logger.warning("batch stopped on failed task task_id=%s", result["task_id"])
                break

        _log_action_group_summary(entries)
        report = write_report(
            root,
            entries,
            markdown=report_config.markdown,
            json_report=report_config.json_report,
            include_prompt_preview=report_config.include_prompt_preview,
            include_png_params_summary=report_config.include_png_params_summary,
            visual_check_template=report_config.visual_check_template,
        )
        logger.info("batch report written run_dir=%s counts=%s", root, report["counts"])
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
                entry = self._handle_execution_result(
                    root=root,
                    task=task,
                    attempt=attempt,
                    result=result,
                )
                if retry_records:
                    entry["retry_records"] = retry_records
                return entry
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
                logger.warning(
                    "batch task retry scheduled task_id=%s attempt=%s/%s delay=%s error=%s",
                    task.id,
                    attempt,
                    max_attempts,
                    delay,
                    last_error,
                )
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
            logger.info("batch task requires_agent task_id=%s source=%s", task.id, _source_log(task))
            return self._record(
                run_dir=root,
                task=task,
                status="requires_agent",
                attempt=attempt,
                image_paths=[],
                error=None,
            )
        if result.status != "succeeded":
            logger.error("batch task failed task_id=%s error=%s", task.id, result.error)
            return self._record(
                run_dir=root,
                task=task,
                status="failed",
                attempt=attempt,
                image_paths=[],
                error=result.error or f"unexpected status: {result.status}",
            )
        if result.prompt_bundle is None or result.render_request is None or result.generation_result is None:
            logger.error("batch task failed incomplete artifacts task_id=%s", task.id)
            return self._record(
                run_dir=root,
                task=task,
                status="failed",
                attempt=attempt,
                image_paths=[],
                error="executor returned incomplete success artifacts",
            )
        if not result.generation_result.png_info:
            logger.error("batch task failed missing png_info task_id=%s", task.id)
            return self._record(
                run_dir=root,
                task=task,
                status="failed",
                attempt=attempt,
                image_paths=result.image_paths,
                error="executor returned success without PNG parameter evidence",
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
        logger.info(
            "batch task succeeded task_id=%s image_count=%s images=%s source=%s",
            task.id,
            len(entry["image_paths"]),
            entry["image_paths"],
            _source_log(task),
        )
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
            "source": task.source,
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
            "source": task.source,
        }


def _task_with_image_budget(task: BatchTask, image_budget: int | None) -> BatchTask:
    if image_budget is None or image_budget >= task.render.nt:
        return task
    return task.model_copy(
        deep=True,
        update={"render": task.render.model_copy(update={"nt": max(1, image_budget)})},
    )


def _resume_task_snapshot(task: BatchTask) -> BatchTask:
    task_path = Path(task.output.task_dir) / "task.json"
    if not task_path.exists():
        return task
    try:
        return BatchTask.model_validate(json.loads(task_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return task


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


def _source_log(task: BatchTask) -> dict[str, Any]:
    source = task.source or {}
    return {
        "character": _basename(source.get("character")),
        "action_group": source.get("action_group"),
        "action": _basename(source.get("action")),
        "artist": source.get("artist") or task.render.artist,
    }


def _basename(value: Any) -> Any:
    if value is None:
        return None
    return Path(str(value)).name


def _log_action_group_summary(entries: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str], dict[str, int]] = {}
    for entry in entries:
        source = entry.get("source") or {}
        group = source.get("action_group")
        character = source.get("character")
        if not group or not character:
            continue
        key = (_basename(character), str(group))
        counts = grouped.setdefault(key, {"succeeded": 0, "failed": 0, "other": 0})
        status = str(entry.get("status") or "unknown")
        if status == "succeeded":
            counts["succeeded"] += 1
        elif status == "failed":
            counts["failed"] += 1
        else:
            counts["other"] += 1
    for (character, group), counts in grouped.items():
        logger.info(
            "action group completed character=%s group=%s succeeded=%s failed=%s other=%s",
            character,
            group,
            counts["succeeded"],
            counts["failed"],
            counts["other"],
        )
