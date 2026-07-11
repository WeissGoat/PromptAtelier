from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from tags_machine_core.batch import (
    BatchPlanner,
    BatchRunner,
    BatchSpec,
    load_batch_spec,
    load_batch_spec_mapping,
)
from tags_machine_core.config import build_prompt_policy_provider, load_config
from tags_machine_core.json_tools import to_jsonable
from tags_machine_core.web.services.job_manager import JobContext


class BatchWorkspace:
    def __init__(self, *, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def preview(self, data: dict[str, Any]) -> dict[str, Any]:
        spec, spec_path, inline = self._load_spec(data)
        run_id = self._run_id(data)
        run_dir = self._run_dir(spec, data=data, spec_path=spec_path)
        output_dir = self._output_dir(spec, data=data, spec_path=spec_path, run_dir=run_dir)
        tasks = self._plan_tasks(
            spec,
            spec_path=spec_path,
            run_dir=run_dir,
            output_dir=output_dir,
            run_id=run_id,
            config_override=_optional_string(data, "config"),
        )
        sample_limit = _optional_int(data, "sample_limit") or 100
        return {
            "schema": "tags-machine-core.web.batch-preview/v1",
            "batch": spec.name,
            "run_id": run_id,
            "inline": inline,
            "task_count": len(tasks),
            "selector_summary": _selector_summary(tasks),
            "run_dir": str(run_dir),
            "output_dir": str(output_dir),
            "sample_tasks": [to_jsonable(task) for task in tasks[:sample_limit]],
        }

    def run(self, data: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        spec, spec_path, inline = self._load_spec(data)
        spec = _spec_with_overrides(
            spec,
            resume=_optional_bool(data, "resume"),
            stop_on_error=_optional_bool(data, "stop_on_error"),
            fresh=_optional_bool(data, "fresh"),
            execution_mode=_optional_string(data, "execution_mode"),
        )
        run_dir = self._run_dir(spec, data=data, spec_path=spec_path)
        run_id = self._run_id(data, fallback_run_dir=run_dir, fresh=spec.run.fresh)
        output_dir = self._output_dir(spec, data=data, spec_path=spec_path, run_dir=run_dir)
        tasks = self._plan_tasks(
            spec,
            spec_path=spec_path,
            run_dir=run_dir,
            output_dir=output_dir,
            run_id=run_id,
            config_override=_optional_string(data, "config"),
        )
        limit = _optional_int(data, "limit")
        config_path = self._config_path(spec, spec_path=spec_path, override=_optional_string(data, "config"))
        config = load_config(config_path)

        self._archive_source(
            run_dir,
            spec_path=spec_path,
            spec=spec,
            inline=inline,
            run_id=run_id,
            output_dir=output_dir,
        )
        ctx.emit(
            "batch_planned",
            {
                "batch": spec.name,
                "run_id": run_id,
                "task_count": len(tasks),
                "limit": limit,
                "run_dir": str(run_dir),
                "output_dir": str(output_dir),
            },
        )
        result = BatchRunner().run_tasks(
            run_dir=run_dir,
            tasks=tasks,
            config=config,
            run_config=spec.run,
            archive_config=spec.archive,
            report_config=spec.report,
            limit=limit,
        )
        return {
            "schema": "tags-machine-core.web.batch-run-result/v1",
            "batch": spec.name,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "output_dir": str(output_dir),
            **to_jsonable(result),
        }

    def resume(self, data: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        if not _optional_string(data, "run_dir"):
            raise ValueError("batch resume requires run_dir")
        request = dict(data)
        request["resume"] = True
        return self.run(request, ctx)

    def _load_spec(self, data: dict[str, Any]) -> tuple[BatchSpec, Path, bool]:
        inline_spec = data.get("spec") or data.get("batch")
        if inline_spec is not None:
            if not isinstance(inline_spec, dict):
                raise ValueError("inline batch spec must be an object")
            spec_path = self.base_dir / "inline_batch.yaml"
            return load_batch_spec_mapping(inline_spec, base_path=spec_path), spec_path, True

        raw_path = _optional_string(data, "batch_spec") or _optional_string(data, "spec_path")
        if not raw_path:
            raise ValueError("batch request requires batch_spec or spec")
        spec_path = self._resolve_path(raw_path)
        return load_batch_spec(spec_path), spec_path, False

    def _plan_tasks(
        self,
        spec: BatchSpec,
        *,
        spec_path: Path,
        run_dir: Path,
        output_dir: Path,
        run_id: str,
        config_override: str | None,
    ):
        config_path = self._config_path(
            spec,
            spec_path=spec_path,
            override=config_override,
        )
        config = load_config(config_path)
        provider = build_prompt_policy_provider(config, config_path=config_path)
        return BatchPlanner(
            base_dir=spec_path.parent,
            policy_provider=provider,
        ).plan(
            spec,
            run_dir=run_dir,
            output_dir=output_dir,
            run_id=run_id,
        )

    def _run_dir(self, spec: BatchSpec, *, data: dict[str, Any], spec_path: Path) -> Path:
        work_root = _optional_string(data, "work_root") or spec.work_root
        output_root = _optional_string(data, "output_root") or spec.output_root
        if work_root:
            return _relative_path(work_root, spec_path=spec_path) / spec.name
        if output_root:
            return _relative_path(output_root, spec_path=spec_path) / spec.name
        return spec_path.parent / spec.name

    def _output_dir(
        self,
        spec: BatchSpec,
        *,
        data: dict[str, Any],
        spec_path: Path,
        run_dir: Path,
    ) -> Path:
        raw = _optional_string(data, "output_dir") or spec.output_dir
        if raw:
            return _relative_path(raw, spec_path=spec_path)
        return run_dir / "outputs"

    def _config_path(self, spec: BatchSpec, *, spec_path: Path, override: str | None) -> Path:
        if override:
            return self._resolve_path(override)
        raw = Path(spec.config)
        if raw.is_absolute():
            return raw
        if raw.exists():
            return raw
        return spec_path.parent / raw

    def _run_id(
        self,
        data: dict[str, Any],
        *,
        fallback_run_dir: Path | None = None,
        fresh: bool = False,
    ) -> str:
        value = _optional_string(data, "run_id")
        if value:
            return value
        if fallback_run_dir is not None and not fresh:
            source_path = fallback_run_dir / "batch_source.json"
            if source_path.exists():
                try:
                    source_data = json.loads(source_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    source_data = {}
                run_id = source_data.get("run_id")
                if isinstance(run_id, str) and run_id.strip():
                    return run_id.strip()
        return uuid4().hex[:8]

    def _archive_source(
        self,
        run_dir: str | Path,
        *,
        spec_path: Path,
        spec: BatchSpec,
        inline: bool,
        run_id: str,
        output_dir: str | Path,
    ) -> None:
        root = Path(run_dir)
        root.mkdir(parents=True, exist_ok=True)
        if inline:
            (root / "batch.yaml").write_text(
                yaml.safe_dump(
                    spec.model_dump(by_alias=True, mode="json"),
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            source = "inline_api_request"
        else:
            shutil.copy2(spec_path, root / "batch.yaml")
            source = "file"
        (root / "batch_source.json").write_text(
            json.dumps(
                {
                    "schema": "tags-machine-core.batch-source/v1",
                    "source": source,
                    "spec_path": str(spec_path.resolve()),
                    "run_id": run_id,
                    "work_root": str(root.resolve()),
                    "output_dir": str(Path(output_dir).resolve()),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _resolve_path(self, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        candidate = self.base_dir / path
        return candidate if candidate.exists() else path


def _relative_path(value: str | Path, *, spec_path: Path | None) -> Path:
    path = Path(value)
    if path.is_absolute() or spec_path is None:
        return path
    return spec_path.parent / path


def _spec_with_overrides(
    spec: BatchSpec,
    *,
    resume: bool | None,
    stop_on_error: bool | None,
    fresh: bool | None,
    execution_mode: str | None,
) -> BatchSpec:
    run_config = spec.run
    updates: dict[str, Any] = {}
    if resume is not None:
        updates["resume"] = resume
    if stop_on_error is not None:
        updates["stop_on_error"] = stop_on_error
    if fresh is not None:
        updates["fresh"] = fresh
    if execution_mode is not None:
        updates["execution_mode"] = execution_mode
    if updates:
        run_config = run_config.model_copy(update=updates)
    return spec.model_copy(update={"run": run_config})


def _selector_summary(tasks) -> dict[str, Any]:
    role_counts = Counter()
    artist_counts = Counter()
    action_group_counts = Counter()
    composer_counts = Counter()
    for task in tasks:
        composer_counts[task.composer] += 1
        if task.render.artist:
            artist_counts[task.render.artist] += 1
        if task.source.get("action_group"):
            action_group_counts[task.source["action_group"]] += 1
        for node in task.nodes:
            role_counts[node.role] += 1
    return {
        "tasks": len(tasks),
        "composers": dict(composer_counts),
        "node_roles": dict(role_counts),
        "artists": dict(artist_counts),
        "action_groups": dict(action_group_counts),
    }


def _optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(data: dict[str, Any], key: str) -> bool | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean")


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None or value == "":
        return None
    return int(value)
