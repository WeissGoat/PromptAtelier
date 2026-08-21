from __future__ import annotations

import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image

from ..config import load_workspace
from ..integrations.anr_mosaic import AnrAutoMosaicsAdapter
from ..processing import ImageProcessingPipeline
from ..processing.operations import default_operation_registry
from ..tasks.models import SelectionSnapshot, SelectionName
from ..tasks.paths import TaskPaths
from ..tasks.repository import TaskRepository
from ..tasks.scanner import CurrentSelectionScanner, SelectionValidator
from .models import BuildManifest, BuildProgress, BuildResult, ProgressCallback


class PackageBuilder:
    def __init__(self, pipeline: ImageProcessingPipeline | None = None):
        self.pipeline = pipeline

    def build(
        self,
        root: str | Path,
        task_id: str,
        *,
        progress: ProgressCallback | None = None,
    ) -> BuildResult:
        paths, workspace_config = load_workspace(root)
        task_paths = TaskPaths.from_workspace(paths, task_id)
        return self.build_paths(
            task_paths,
            workspace_config=workspace_config,
            progress=progress,
        )

    def build_paths(
        self,
        task_paths: TaskPaths,
        *,
        output_root: str | Path | None = None,
        workspace_config=None,
        progress: ProgressCallback | None = None,
    ) -> BuildResult:
        paths, loaded_config = load_workspace(task_paths.workspace.root)
        workspace_config = workspace_config or loaded_config
        config = TaskRepository.load(task_paths)
        task_paths.ensure_layout()
        build_id = _build_id()
        builds_root = Path(output_root) if output_root is not None else task_paths.builds_root
        builds_root.mkdir(parents=True, exist_ok=True)
        build_root = builds_root / build_id
        temporary = builds_root / f".{build_id}.tmp"
        if build_root.exists() or temporary.exists():
            raise ValueError(f"build 目录已存在：{build_id}")

        selections = CurrentSelectionScanner().scan(
            task_paths,
            set(workspace_config.image_extensions),
        )
        if not selections["all"]:
            raise ValueError("all 选择集合为空，无法构建投稿包")

        total_items = sum(len(items) for items in selections.values())
        if progress is not None:
            progress(
                BuildProgress(
                    phase="validate",
                    processed=0,
                    total=total_items,
                )
            )

        _validate_input_images(selections)
        warnings = SelectionValidator().validate(selections)
        snapshot = SelectionSnapshot(build_id=build_id, selections=selections)
        temporary.mkdir(parents=True, exist_ok=False)
        output_root = temporary / "output"
        output_paths = {
            selection: output_root / selection
            for selection in ("all", "post", "cover")
        }
        for path in output_paths.values():
            path.mkdir(parents=True, exist_ok=True)

        try:
            _write_json_atomic(
                temporary / "selection_snapshot.json",
                snapshot.model_dump(mode="json", by_alias=True),
            )
            pipeline = self.pipeline or _default_pipeline(paths, workspace_config)
            stats = {
                "cache_hit": 0,
                "processed": 0,
                "skipped_mosaic": 0,
            }
            processed_count = 0
            for selection, items in selections.items():
                for item in items:
                    result = pipeline.process(
                        item.absolute_path,
                        output_paths[selection] / item.filename,
                        config.processing,
                    )
                    processed_count += 1
                    if progress is not None:
                        progress(
                            BuildProgress(
                                phase="process",
                                processed=processed_count,
                                total=total_items,
                                current_selection=selection,
                                current_filename=item.filename,
                            )
                        )
                    if result.cache_hit:
                        stats["cache_hit"] += 1
                    else:
                        stats["processed"] += 1
                    if "mosaic" in result.skipped_operations:
                        stats["skipped_mosaic"] += 1

            archive_paths: dict[SelectionName, Path] = {}
            if config.packages.zip.enabled:
                archives_root = temporary / "archives"
                archives_root.mkdir(parents=True, exist_ok=True)
                for selection in config.packages.zip.targets:
                    archive = archives_root / f"{selection}.zip"
                    _write_zip(archive, output_paths[selection])
                    archive_paths[selection] = archive
                    if progress is not None:
                        progress(
                            BuildProgress(
                                phase="archive",
                                processed=processed_count,
                                total=total_items,
                                current_selection=selection,
                            )
                        )

            selection_counts = {
                "candidates": _candidate_count(task_paths),
                **{selection: len(items) for selection, items in selections.items()},
            }
            output_counts = {
                selection: len(items) for selection, items in selections.items()
            }
            manifest = BuildManifest(
                build_id=build_id,
                task_id=task_paths.task_id,
                status="success",
                processing_profile=config.processing.profile,
                selection=selection_counts,
                outputs=output_counts,
                processing_result=stats,
                warnings=warnings,
                errors=[],
            )
            manifest_path = temporary / "build_manifest.json"
            _write_json_atomic(
                manifest_path,
                manifest.model_dump(mode="json", by_alias=True),
            )
            os.replace(temporary, build_root)

            if progress is not None:
                progress(
                    BuildProgress(
                        phase="finalize",
                        processed=total_items,
                        total=total_items,
                    )
                )

            formal_output_paths = {
                selection: build_root / "output" / selection
                for selection in output_paths
            }
            formal_archive_paths = {
                selection: build_root / "archives" / f"{selection}.zip"
                for selection in archive_paths
            }
            return BuildResult(
                build_id=build_id,
                build_root=build_root,
                manifest_path=build_root / "build_manifest.json",
                output_paths=formal_output_paths,
                archive_paths=formal_archive_paths,
                selection=selection_counts,
            )
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise


def _build_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{uuid4().hex[:6]}"


def _default_pipeline(paths, workspace_config) -> ImageProcessingPipeline:
    mosaic_config = workspace_config.integrations.mosaic
    adapter = AnrAutoMosaicsAdapter(paths, mosaic_config)
    registry = default_operation_registry({adapter.name: adapter})
    return ImageProcessingPipeline(
        cache_root=paths.cache / "processing",
        registry=registry,
    )


def _validate_input_images(selections: dict[SelectionName, list]) -> None:
    for items in selections.values():
        for item in items:
            path = Path(item.absolute_path)
            try:
                with Image.open(path) as image:
                    image.verify()
            except (OSError, ValueError) as exc:
                raise ValueError(f"图片无法读取：{path}：{exc}") from exc


def _candidate_count(task_paths: TaskPaths) -> int:
    if not task_paths.candidates_snapshot.is_file():
        return 0
    try:
        data = json.loads(task_paths.candidates_snapshot.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    items = data.get("items") if isinstance(data, dict) else None
    return len(items) if isinstance(items, list) else 0


def _write_zip(archive: Path, directory: Path) -> None:
    temporary = archive.with_name(f".{archive.name}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
                if path.is_file():
                    output.write(path, arcname=path.name)
        os.replace(temporary, archive)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _write_json_atomic(path: Path, data: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
