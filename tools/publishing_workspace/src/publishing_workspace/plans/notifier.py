from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from ..logging import get_logger


logger = get_logger(__name__)


class SubmissionEvent(BaseModel):
    plan_id: str
    entry_id: str
    title: str
    scheduled_at: datetime
    status: Literal["completed", "failed"]
    build_id: str | None = None
    task_id: str | None = None
    output_root: str | None = None
    post_count: int = 0
    error: str | None = None


class NotificationResult(BaseModel):
    status: Literal["sent", "failed", "disabled"]
    message: str | None = None


class Notifier(Protocol):
    def notify(self, event: SubmissionEvent) -> NotificationResult: ...


class ConsoleNotifier:
    def notify(self, event: SubmissionEvent) -> NotificationResult:
        logger.info(
            "投稿构建通知：plan_id=%s entry_id=%s status=%s build_id=%s output_root=%s",
            event.plan_id,
            event.entry_id,
            event.status,
            event.build_id,
            event.output_root,
        )
        return NotificationResult(status="sent")
