from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from tags_machine_core.contracts import utc_now_iso
from tags_machine_core.json_tools import to_jsonable

from .models import BatchStatus, BatchTask, ManifestEntry


def write_initial_manifest(run_dir: str | Path, tasks: list[BatchTask]) -> Path:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.jsonl"
    entries = [
        ManifestEntry(
            task_id=task.id,
            status="pending",
            attempt=0,
            task_path=_relative(root, Path(task.output.task_dir) / "task.json"),
            status_path=_relative(root, Path(task.output.task_dir) / "status.json"),
            updated_at=utc_now_iso(),
        )
        for task in tasks
    ]
    manifest_path.write_text(
        "".join(json.dumps(to_jsonable(entry), ensure_ascii=False) + "\n" for entry in entries),
        encoding="utf-8",
    )
    write_index(run_dir, entries)
    return manifest_path


def append_manifest_entry(run_dir: str | Path, entry: ManifestEntry) -> None:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.jsonl"
    with manifest_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(to_jsonable(entry), ensure_ascii=False) + "\n")
    write_index(root, latest_manifest_entries(root))


def latest_manifest_entries(run_dir: str | Path) -> list[ManifestEntry]:
    root = Path(run_dir)
    manifest_path = root / "manifest.jsonl"
    if not manifest_path.exists():
        return []
    latest: dict[str, ManifestEntry] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = ManifestEntry.model_validate(json.loads(line))
        latest[entry.task_id] = entry
    return list(latest.values())


def write_index(run_dir: str | Path, entries: list[ManifestEntry]) -> Path:
    root = Path(run_dir)
    latest = {entry.task_id: entry for entry in entries}
    counts = Counter(entry.status for entry in latest.values())
    data = {
        "schema": "tags-machine-core.batch-index/v1",
        "updated_at": utc_now_iso(),
        "counts": dict(counts),
        "tasks": {task_id: to_jsonable(entry) for task_id, entry in latest.items()},
    }
    path = root / "index.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def manifest_entry_for_task(
    *,
    run_dir: str | Path,
    task: BatchTask,
    status: BatchStatus,
    attempt: int,
    image_paths: list[str] | None = None,
    error: str | None = None,
) -> ManifestEntry:
    root = Path(run_dir)
    task_dir = Path(task.output.task_dir)
    generation_path = task_dir / "generation_result.json"
    return ManifestEntry(
        task_id=task.id,
        status=status,
        attempt=attempt,
        task_path=_relative(root, task_dir / "task.json"),
        status_path=_relative(root, task_dir / "status.json"),
        generation_result_path=(
            _relative(root, generation_path) if generation_path.exists() else None
        ),
        image_paths=image_paths or [],
        error=error,
        updated_at=utc_now_iso(),
    )


def task_already_succeeded(task: BatchTask) -> bool:
    status_path = Path(task.output.task_dir) / "status.json"
    if not status_path.exists():
        return False
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return data.get("status") == "succeeded"


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
