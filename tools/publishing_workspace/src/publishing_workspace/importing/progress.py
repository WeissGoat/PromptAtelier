from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .models import ImportCounters


class ProgressReporter:
    def __init__(
        self,
        *,
        logger: logging.Logger,
        every_items: int = 200,
        every_seconds: float = 5.0,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.logger = logger
        self.every_items = every_items
        self.every_seconds = every_seconds
        self.monotonic = monotonic
        self._last_item = 0
        self._last_time = monotonic()

    def emit(
        self,
        event: str,
        *,
        current: int,
        total: int,
        counters: ImportCounters,
        force: bool = False,
    ) -> None:
        now = self.monotonic()
        due = (
            force
            or event.endswith("_started")
            or event.endswith("_completed")
            or current - self._last_item >= self.every_items
            or now - self._last_time >= self.every_seconds
        )
        if not due:
            return
        self._last_item = current
        self._last_time = now
        if event.endswith("_progress"):
            self.logger.info(
                "%s %s/%s reused=%s content_reuse=%s new=%s missing=%s failed=%s held=%s",
                event,
                current,
                total,
                counters.reused_path_items,
                counters.reused_content_items,
                counters.parsed_new_items,
                counters.missing_items,
                counters.failed_items,
                counters.held_problem_items,
            )
        else:
            self.logger.info("%s %s/%s", event, current, total)

    def trace_item(self, *, source_order: int, decision: str, path: str) -> None:
        self.logger.log(5, "item source_order=%s decision=%s path=%s", source_order, decision, path)
