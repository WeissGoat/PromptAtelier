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

_RESET = "\033[0m"
_COLORS: dict[int, str] = {
    TRACE_LEVEL: "\033[38;5;244m",
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[35m",
}


class ColorFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime_colored)s %(levelname_colored)s %(filename_colored)s:%(lineno)d %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelno, "")
        record.message = record.getMessage()
        asctime = self.formatTime(record, self.datefmt)
        record.asctime_colored = _wrap_color(asctime, color)
        record.levelname_colored = _wrap_color(f"{record.levelname:<7}", color)
        record.filename_colored = _wrap_color(record.filename, color)
        message = self.formatMessage(record)
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            if message[-1:] != "\n":
                message += "\n"
            message += record.exc_text
        if record.stack_info:
            if message[-1:] != "\n":
                message += "\n"
            message += self.formatStack(record.stack_info)
        return message


def _wrap_color(text: str, color: str) -> str:
    if not color:
        return text
    return f"{color}{text}{_RESET}"


_DEFAULT_FORMATTER = ColorFormatter()


def format_console_record(
    *,
    level: int,
    logger_name: str,
    pathname: str,
    lineno: int,
    message: str,
) -> str:
    record = logging.LogRecord(
        name=logger_name,
        level=level,
        pathname=pathname,
        lineno=lineno,
        msg=message,
        args=(),
        exc_info=None,
    )
    return _DEFAULT_FORMATTER.format(record)


def emit_console_record(
    *,
    level: int,
    logger_name: str,
    pathname: str,
    lineno: int,
    message: str,
) -> None:
    print(
        format_console_record(
            level=level,
            logger_name=logger_name,
            pathname=pathname,
            lineno=lineno,
            message=message,
        ),
        file=sys.stderr,
        flush=True,
    )


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
        handler.setFormatter(_DEFAULT_FORMATTER)
        logger.addHandler(handler)

    for handler in logger.handlers:
        handler.setLevel(level_number)
    return level_number


def get_logger(name: str) -> logging.Logger:
    _install_trace_level()
    return logging.getLogger(name)
