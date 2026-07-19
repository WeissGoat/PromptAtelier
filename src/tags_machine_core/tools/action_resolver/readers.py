from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from tags_machine_core.tools.task_tools.resolver import TaskArchiveResolver

from .models import ActionEvidence


def read_task_evidence(task_dir: str | Path) -> list[ActionEvidence]:
    task_path = Path(task_dir).resolve()
    try:
        context = TaskArchiveResolver().resolve_one(task_path)
    except Exception as exc:
        return [
            ActionEvidence(
                input_path=task_path,
                source_kind="core_task",
                source_detail="task archive",
                error=str(exc),
            )
        ]

    evidence: list[ActionEvidence] = []
    for resource in context.resources_for("action"):
        ref = resource.ref or (str(resource.path) if resource.path else "")
        action = resource.id or Path(ref).name
        evidence.append(
            ActionEvidence(
                input_path=task_path,
                source_kind="core_task",
                action=action,
                topic=_topic_from_ref(ref),
                ref=ref or None,
                source_detail=resource.source,
            )
        )
    if not evidence:
        evidence.append(
            ActionEvidence(
                input_path=task_path,
                source_kind="core_task",
                source_detail="task archive",
            )
        )
    return _deduplicate_evidence(evidence)


def read_image_evidence(image_path: str | Path) -> ActionEvidence:
    path = Path(image_path).resolve()
    try:
        with Image.open(path) as image:
            info = {str(key).casefold(): value for key, value in image.info.items()}
    except Exception as exc:
        return ActionEvidence(
            input_path=path,
            source_kind="legacy_image",
            source_detail="image metadata",
            error=str(exc),
        )

    action = clean_text(info.get("action"))
    topic = clean_text(info.get("topic"))
    comment = clean_text(info.get("comment"))
    if comment:
        try:
            parsed = json.loads(comment)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            action = action or clean_text(parsed.get("action"))
            topic = topic or clean_text(parsed.get("topic"))

    return ActionEvidence(
        input_path=path,
        source_kind="legacy_image",
        action=action,
        topic=topic,
        source_detail="PNG/JPEG/WebP metadata",
    )


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip()


def _topic_from_ref(ref: str) -> str:
    normalized = ref.replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) < 2:
        return ""
    parent = parts[-2]
    return "" if parent == "new" else parent


def _deduplicate_evidence(items: list[ActionEvidence]) -> list[ActionEvidence]:
    result: list[ActionEvidence] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in items:
        key = (item.source_kind, item.action, item.topic, item.ref or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
