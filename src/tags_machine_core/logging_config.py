from __future__ import annotations

import logging
import os
import sys
from typing import Literal


TRACE_LEVEL = 5
DEFAULT_LOG_LEVEL = "error"
LOG_LEVEL_ENV = "TAGS_MACHINE_CORE_LOG_LEVEL"
LogLevelName = Literal["trace", "info", "warning", "error"]

_LEVELS: dict[str, int] = {
    "trace": TRACE_LEVEL,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def _install_trace_level() -> None:
    if logging.getLevelName(TRACE_LEVEL) != "TRACE":
        logging.addLevelName(TRACE_LEVEL, "TRACE")

    if not hasattr(logging.Logger, "trace"):

        def trace(self: logging.Logger, message, *args, **kwargs) -> None:
            if self.isEnabledFor(TRACE_LEVEL):
                self._log(TRACE_LEVEL, message, args, **kwargs)

        logging.Logger.trace = trace  # type: ignore[attr-defined]


def normalize_log_level(level: str | None) -> int:
    raw = (level or os.environ.get(LOG_LEVEL_ENV) or DEFAULT_LOG_LEVEL).strip().lower()
    if raw not in _LEVELS:
        valid = ", ".join(["trace", "info", "warning", "error"])
        raise ValueError(f"Unsupported log level: {level!r}. Expected one of: {valid}")
    return _LEVELS[raw]


def configure_logging(level: str | None = None) -> int:
    _install_trace_level()
    level_number = normalize_log_level(level)
    logger = logging.getLogger("tags_machine_core")
    logger.setLevel(level_number)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(handler)

    for handler in logger.handlers:
        handler.setLevel(level_number)
    return level_number


def get_logger(name: str) -> logging.Logger:
    _install_trace_level()
    return logging.getLogger(name)
