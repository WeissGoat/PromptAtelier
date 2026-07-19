import json
from pathlib import Path
from typing import Any, Sequence

from .models import RelatedResource, TaskContext, TaskContextSet


class TaskArchiveError(RuntimeError):
    """任务归档定位或读取失败。"""


class TaskArchiveNotFoundError(TaskArchiveError):
    """输入路径向上找不到受支持的任务归档。"""


class TaskArchiveReadError(TaskArchiveError):
    """任务归档存在但无法按 UTF-8 JSON 对象读取。"""


class TaskArchiveResolver:
    archive_names = (
        "render_request.json",
        "prompt_bundle.json",
        "generation_result.json",
    )

    def resolve(self, inputs: Sequence[str | Path]) -> TaskContextSet:
        tasks: list[TaskContext] = []
        seen: set[str] = set()
        for value in inputs:
            context = self.resolve_one(value)
            key = str(context.task_dir).casefold()
            if key in seen:
                continue
            seen.add(key)
            tasks.append(context)
        if not tasks:
            raise TaskArchiveNotFoundError("没有收到可解析的任务路径")
        return TaskContextSet(tasks=tasks)

    def resolve_one(self, input_path: str | Path) -> TaskContext:
        selected = Path(input_path).resolve(strict=True)
        task_dir = self.find_task_dir(selected)
        archive_files = {
            name: task_dir / name
            for name in self.archive_names
            if (task_dir / name).is_file()
        }
        loaded = {name: _read_json(path) for name, path in archive_files.items()}
        render_request = loaded.get("render_request.json")
        prompt_bundle = loaded.get("prompt_bundle.json")
        resources = _merge_resources(
            _resources_from_render_request(render_request or {}),
            _resources_from_prompt_bundle(prompt_bundle or {}),
        )
        return TaskContext(
            input_path=selected,
            task_dir=task_dir,
            archive_files=archive_files,
            resources=resources,
            render_request=render_request,
            prompt_bundle=prompt_bundle,
            generation_result=loaded.get("generation_result.json"),
        )

    def find_task_dir(self, input_path: str | Path) -> Path:
        selected = Path(input_path).resolve(strict=True)
        start = selected if selected.is_dir() else selected.parent
        for candidate in (start, *start.parents):
            if any((candidate / name).is_file() for name in self.archive_names):
                return candidate
        raise TaskArchiveNotFoundError(f"找不到任务归档目录：{selected}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TaskArchiveReadError(f"无法读取任务归档：{path}：{exc}") from exc
    if not isinstance(value, dict):
        raise TaskArchiveReadError(f"任务归档顶层必须是对象：{path}")
    return value


def _resource_index(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _resources_from_render_request(data: dict[str, Any]) -> list[RelatedResource]:
    resources: list[RelatedResource] = []
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    node_refs = meta.get("node_refs") if isinstance(meta.get("node_refs"), list) else []
    for fallback_index, item in enumerate(node_refs):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if not role:
            continue
        ref = str(item.get("ref") or "").strip() or None
        path = Path(ref) if ref and Path(ref).is_absolute() else None
        resources.append(
            RelatedResource(
                role=role,
                id=str(item.get("id") or "").strip() or None,
                ref=ref,
                path=path,
                index=_resource_index(item.get("index"), fallback_index),
                source="render_request.meta.node_refs",
            )
        )
    artist = data.get("artist_payload") if isinstance(data.get("artist_payload"), dict) else {}
    artist_path = str(artist.get("path") or "").strip()
    if artist_path:
        artist_ref = str(artist.get("artist_ref") or "").strip() or None
        resources.append(
            RelatedResource(
                role="artist",
                id=artist_ref,
                ref=artist_ref,
                path=Path(artist_path),
                source="render_request.artist_payload.path",
            )
        )
    return resources


def _resources_from_prompt_bundle(data: dict[str, Any]) -> list[RelatedResource]:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    nodes = meta.get("nodes") if isinstance(meta.get("nodes"), list) else []
    resources: list[RelatedResource] = []
    for fallback_index, item in enumerate(nodes):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if not role:
            continue
        ref = str(item.get("ref") or "").strip() or None
        path = Path(ref) if ref and Path(ref).is_absolute() else None
        resources.append(
            RelatedResource(
                role=role,
                id=str(item.get("id") or "").strip() or None,
                ref=ref,
                path=path,
                index=_resource_index(item.get("index"), fallback_index),
                source="prompt_bundle.meta.nodes",
            )
        )
    return resources


def _normalized_location(resource: RelatedResource) -> str | None:
    if resource.path is not None:
        return str(resource.path.resolve()).casefold()
    if resource.ref:
        return str(Path(resource.ref).expanduser().resolve()).casefold()
    return None


def _merge_resources(*groups: list[RelatedResource]) -> list[RelatedResource]:
    merged: dict[tuple[str, int, str], RelatedResource] = {}
    order: list[tuple[str, int, str]] = []
    for group in groups:
        for resource in group:
            location = _normalized_location(resource)
            identity = f"path:{location}" if location is not None else f"id:{resource.id or ''}".casefold()
            key = (resource.role, resource.index, identity)
            previous = merged.get(key)
            if previous is None:
                order.append(key)
                merged[key] = resource
            elif previous.path is None and resource.path is not None:
                merged[key] = resource
    return [merged[key] for key in order]
