"""BatchTask 的稳定指纹，供 AlbumPlan resume 检查使用。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import BatchTask


def task_fingerprint(task: BatchTask) -> str:
    """忽略运行目录和 run_id，保留会影响实际出图的输入。"""

    source = dict(task.source)
    for field in ("run_id", "album_plan_path"):
        source.pop(field, None)
    payload = {
        "composer": task.composer,
        "prompt": task.prompt,
        "negative": task.negative,
        "extra_prompt": task.extra_prompt,
        "nodes": [_node_payload(node.ref, node.role, node.index) for node in task.nodes],
        "render": task.render.model_dump(mode="json", exclude={"output_dir"}),
        "agent": task.agent.model_dump(mode="json"),
        "composition": task.composition.model_dump(mode="json"),
        "policy": task.policy.model_dump(mode="json") if task.policy else None,
        "artist_input_filter": (
            task.artist_input_filter.model_dump(mode="json") if task.artist_input_filter else None
        ),
        "source": source,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _node_payload(ref: str, role: str, index: int) -> dict[str, Any]:
    return {
        "role": role,
        "index": index,
        "ref": ref,
        "content_hash": _node_content_hash(ref),
    }


def _node_content_hash(ref: str) -> str:
    path = Path(ref)
    if not path.is_dir():
        return "sha256:" + hashlib.sha256(ref.encode("utf-8")).hexdigest()
    digest = hashlib.sha256()
    found = False
    for filename in ("meta.yaml", "node.yaml", "tags.txt"):
        source = path / filename
        if not source.is_file():
            continue
        found = True
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    if not found:
        digest.update(str(path).encode("utf-8"))
    return "sha256:" + digest.hexdigest()
