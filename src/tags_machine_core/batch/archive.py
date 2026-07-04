from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from tags_machine_core.contracts import GeneratedImage, GenerationResult, utc_now_iso
from tags_machine_core.json_tools import to_jsonable

from .models import ArchiveConfig, BatchStatus, BatchTask
from .parameter_image import write_parameter_details_image


logger = logging.getLogger(__name__)
PARAMETER_DETAILS_IMAGE_PREFIX = "zz"


class BatchArchive:
    def __init__(self, config: ArchiveConfig | None = None):
        self.config = config or ArchiveConfig()

    def write_task(self, task: BatchTask) -> Path:
        return self.write_json(task, "task.json", task, target_dir=Path(task.output.task_dir))

    def write_status(
        self,
        task: BatchTask,
        *,
        status: BatchStatus,
        attempt: int,
        image_paths: list[str] | None = None,
        error: str | None = None,
        warning: str | None = None,
    ) -> Path:
        data = {
            "schema": "tags-machine-core.batch-task-status/v1",
            "task_id": task.id,
            "status": status,
            "attempt": attempt,
            "render": to_jsonable(task.render),
            "image_paths": image_paths or [],
            "error": error,
            "warning": warning,
            "updated_at": utc_now_iso(),
        }
        return self.write_json(task, "status.json", data, target_dir=Path(task.output.task_dir))

    def write_agent_task(self, *, run_dir: str | Path, task: BatchTask, value: Any) -> Path:
        self.write_json(task, "agent_task.json", value, target_dir=Path(task.output.task_dir))
        path = Path(run_dir) / "agent_tasks" / f"{task.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(to_jsonable(value), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def archive_success(
        self,
        *,
        task: BatchTask,
        prompt_bundle: Any,
        render_request: Any,
        generation_result: GenerationResult,
    ) -> GenerationResult:
        result = (
            self._copy_images_to_artifact_dir(task, generation_result)
            if self.config.copy_images
            else generation_result
        )
        if self.config.save_prompt_bundle:
            self.write_json(task, "prompt_bundle.json", prompt_bundle, target_dir=self._artifact_dir(task))
        if self.config.save_render_request:
            self.write_json(task, "render_request.json", render_request, target_dir=self._artifact_dir(task))
        if self.config.save_generation_result:
            self.write_json(task, "generation_result.json", result, target_dir=self._artifact_dir(task))
        if self.config.save_png_params:
            self.write_json(task, "png_params.json", result.png_info, target_dir=self._artifact_dir(task))
        if self.config.save_parameter_image:
            self._write_parameter_image(
                task=task,
                prompt_bundle=prompt_bundle,
                render_request=render_request,
                generation_result=result,
            )
        self.write_json(
            task,
            "images.json",
            {
                "images": [
                    {
                        "path": str(image.path),
                        "filename": image.filename,
                        "meta": image.meta,
                    }
                    for image in result.images
                ]
            },
            target_dir=self._artifact_dir(task),
        )
        return result

    def _write_parameter_image(
        self,
        *,
        task: BatchTask,
        prompt_bundle: Any,
        render_request: Any,
        generation_result: GenerationResult,
    ) -> Path | None:
        path = self._artifact_dir(task) / parameter_details_image_filename(task.id)
        try:
            return write_parameter_details_image(
                path,
                task=task,
                prompt_bundle=prompt_bundle,
                render_request=render_request,
                generation_result=generation_result,
            )
        except Exception as exc:
            logger.warning(
                "failed to write parameter details image task_id=%s path=%s error=%s",
                task.id,
                path,
                exc,
            )
            return None

    def write_json(self, task: BatchTask, filename: str, value: Any, *, target_dir: Path | None = None) -> Path:
        task_dir = target_dir or self._artifact_dir(task)
        task_dir.mkdir(parents=True, exist_ok=True)
        path = task_dir / filename
        path.write_text(json.dumps(to_jsonable(value), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _artifact_dir(self, task: BatchTask) -> Path:
        return Path(task.output.output_dir or task.render.output_dir or task.output.task_dir)

    def _copy_images_to_artifact_dir(
        self,
        task: BatchTask,
        generation_result: GenerationResult,
    ) -> GenerationResult:
        image_dir = self._artifact_dir(task)
        image_dir.mkdir(parents=True, exist_ok=True)
        copied: list[GeneratedImage] = []
        for image in generation_result.images:
            source = Path(image.path)
            target = image_dir / image.filename
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            copied.append(
                image.model_copy(
                    update={
                        "path": target,
                        "filename": target.name,
                        "meta": {**image.meta, "archived_from": str(source)},
                    }
                )
            )
        return generation_result.model_copy(update={"images": copied})


def parameter_details_image_filename(task_id: str) -> str:
    return f"{PARAMETER_DETAILS_IMAGE_PREFIX}_{task_id}_parameter_details.png"
