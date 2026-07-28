from __future__ import annotations

import logging
import os


TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")


def configure_logging(level: str | None = None) -> None:
    selected = (level or os.environ.get("PUBLISHING_WORKSPACE_LOG_LEVEL") or "error").lower()
    numeric = {
        "trace": TRACE_LEVEL,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }.get(selected)
    if numeric is None:
        raise ValueError(f"不支持的日志级别：{selected}")
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
