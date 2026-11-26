"""NovelAI 与批量生成错误的统一分类辅助函数。"""

from __future__ import annotations

import math
import re
from typing import Any

FATAL_HTTP_STATUS_CODES: frozenset[int] = frozenset({401, 402, 403})

_STATUS_CODE_RE = re.compile(
    r"(?:http\s+|status_code[=:\s]+|too many\s+)(\d{3})\b",
    re.IGNORECASE,
)
_RETRY_AFTER_RE = re.compile(
    r"retry[-_\s]?after[:=\s]+(\d+(?:\.\d+)?)s?\b",
    re.IGNORECASE,
)


def _iter_error_chain(error: Exception | str | None):
    if error is None:
        return
    if isinstance(error, Exception):
        seen: set[int] = set()
        current: BaseException | None = error
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            yield current
            current = current.__cause__ or current.__context__
    else:
        yield str(error)


def extract_http_status_code(error: Exception | str | None) -> int | None:
    if error is None:
        return None
    for item in _iter_error_chain(error):
        if isinstance(item, BaseException):
            status_code = getattr(item, "status_code", None)
            if isinstance(status_code, int) and 100 <= status_code <= 599:
                return status_code
            response = getattr(item, "response", None)
            resp_status = getattr(response, "status_code", None)
            if isinstance(resp_status, int) and 100 <= resp_status <= 599:
                return resp_status
            if type(item).__name__ == "RateLimitError":
                return 429

        text = str(item)
        match = _STATUS_CODE_RE.search(text)
        if match:
            code = int(match.group(1))
            if 100 <= code <= 599:
                return code
        if "rate limited" in text.lower():
            return 429
    return None


def extract_retry_after_seconds(error: Exception | str | None) -> float | None:
    if error is None:
        return None
    for item in _iter_error_chain(error):
        if isinstance(item, BaseException):
            retry_after: Any = getattr(item, "retry_after", None)
            if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool):
                val = float(retry_after)
                if math.isfinite(val) and val > 0:
                    return val
        text = str(item)
        match = _RETRY_AFTER_RE.search(text)
        if match:
            val = float(match.group(1))
            if math.isfinite(val) and val > 0:
                return val
    return None


def is_rate_limit_error(error: Exception | str | None) -> bool:
    return extract_http_status_code(error) == 429


def fatal_generation_error_reason(error: Exception | str | None) -> str | None:
    if error is None:
        return None
    status_code = extract_http_status_code(error)
    if status_code == 401:
        return "HTTP 401 (NovelAI token invalid or expired)"
    if status_code == 402:
        return "HTTP 402 (NovelAI payment required / insufficient Anlas or unsupported tier)"
    if status_code == 403:
        return "HTTP 403 (NovelAI forbidden / risk control)"

    for item in _iter_error_chain(error):
        if "missing novelai token" in str(item).lower():
            return "Missing NovelAI token"
    return None


def is_fatal_generation_error(error: Exception | str | None) -> bool:
    return fatal_generation_error_reason(error) is not None


def transport_retries_exhausted(error: Exception | str | None) -> bool:
    if error is None:
        return False
    for item in _iter_error_chain(error):
        text = str(item)
        if "max retries exceeded" in text.lower():
            return True
        if "retry_records=" in text and text.count("RetryRecord(") >= 2:
            return True
    return False
