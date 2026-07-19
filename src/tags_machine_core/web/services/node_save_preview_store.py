from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.web.node_editing import FileMutation


class SavePreviewExpiredError(ValueError):
    pass


class SourceChangedError(ValueError):
    pass


@dataclass
class NodeSavePreview:
    preview_id: str
    ref: str
    role: str
    node: NodeDocument
    mutations: list[FileMutation]
    created_at: float
    expires_at: float


class NodeSavePreviewStore:
    def __init__(self, *, ttl_seconds: int = 600):
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, NodeSavePreview] = {}

    def create(
        self,
        *,
        ref: str,
        role: str,
        node: NodeDocument,
        mutations: list[FileMutation],
    ) -> NodeSavePreview:
        self._purge_expired()
        now = time.time()
        preview = NodeSavePreview(
            preview_id=f"save_{uuid.uuid4().hex}",
            ref=ref,
            role=role,
            node=node,
            mutations=mutations,
            created_at=now,
            expires_at=now + self.ttl_seconds,
        )
        self._items[preview.preview_id] = preview
        return preview

    def get(self, preview_id: str) -> NodeSavePreview:
        preview = self._items.get(preview_id)
        if preview is None or preview.expires_at <= time.time():
            self._items.pop(preview_id, None)
            raise SavePreviewExpiredError("Node save preview expired or was not found")
        return preview

    def consume(self, preview_id: str) -> NodeSavePreview:
        preview = self.get(preview_id)
        self._items.pop(preview_id, None)
        return preview

    def _purge_expired(self) -> None:
        now = time.time()
        for key in [key for key, value in self._items.items() if value.expires_at <= now]:
            self._items.pop(key, None)
