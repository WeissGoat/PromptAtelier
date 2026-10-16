from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, Request

from tags_machine_core.config import AppConfig
from tags_machine_core.services.novelai_usage import (
    NovelAIUsageInfo,
    inquire_novelai_usage,
)

router = APIRouter()

# 简单的内存快照缓存，避免频繁打 NovelAI 导致限流 (GET 端点 60s 缓存)
_CACHE_TTL_SECONDS = 60.0
_usage_cache: dict[str, Any] = {
    "info": None,
    "timestamp": 0.0,
}


def _resolve_token(config: AppConfig) -> str | None:
    token = config.novelai.access_token
    if not token and config.novelai.access_token_env:
        token = os.environ.get(config.novelai.access_token_env)
    return token


def _get_current_usage(request: Request, force_refresh: bool = False) -> NovelAIUsageInfo:
    now = time.time()
    cached_info = _usage_cache.get("info")
    cached_time = _usage_cache.get("timestamp", 0.0)

    if not force_refresh and cached_info is not None and (now - cached_time) < _CACHE_TTL_SECONDS:
        return cached_info

    config: AppConfig = request.app.state.config
    token = _resolve_token(config)
    base_url = config.novelai.base_url or "https://image.novelai.net"

    info = inquire_novelai_usage(token, base_url=base_url)
    _usage_cache["info"] = info
    _usage_cache["timestamp"] = now
    return info


@router.get("/novelai/usage", response_model=NovelAIUsageInfo)
def get_novelai_usage(request: Request) -> NovelAIUsageInfo:
    """获取当前 NovelAI 账号会员状态与 V5 用量快照（带 60s 缓存）。"""
    return _get_current_usage(request, force_refresh=False)


@router.post("/novelai/usage/refresh", response_model=NovelAIUsageInfo)
def refresh_novelai_usage(request: Request) -> NovelAIUsageInfo:
    """强制重新向 NovelAI 官方查询会员状态与用量快照并更新缓存。"""
    return _get_current_usage(request, force_refresh=True)
