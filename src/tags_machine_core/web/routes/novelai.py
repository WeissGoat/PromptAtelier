from __future__ import annotations

import os
import threading
import time
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from tags_machine_core.config import AppConfig
from tags_machine_core.services.novelai_usage import (
    NovelAIUsageInfo,
    inquire_novelai_usage,
)

from ..errors import ApiError
from ..services.novelai_tokens import NovelAITokenStore, TokenStoreError

router = APIRouter()

# 按 token 缓存用量快照，避免频繁打 NovelAI 导致限流 (GET 端点 60s 缓存)
_CACHE_TTL_SECONDS = 60.0
_usage_cache: dict[str, tuple[float, NovelAIUsageInfo]] = {}
_cache_lock = threading.Lock()


def resolve_config_token(config: AppConfig) -> str | None:
    token = config.novelai.access_token
    if not token and config.novelai.access_token_env:
        token = os.environ.get(config.novelai.access_token_env)
    return token


def _store(request: Request) -> NovelAITokenStore:
    return request.app.state.novelai_tokens


def _usage_for(
    request: Request,
    entry: dict[str, Any] | None,
    *,
    force_refresh: bool,
) -> NovelAIUsageInfo:
    if entry is None:
        return inquire_novelai_usage(None)
    token = entry["token"]
    now = time.time()
    with _cache_lock:
        cached = _usage_cache.get(token)
    if not force_refresh and cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
        info = cached[1]
    else:
        config: AppConfig = request.app.state.config
        base_url = config.novelai.base_url or "https://image.novelai.net"
        info = inquire_novelai_usage(token, base_url=base_url)
        # 查失败（限流、网络、token 失效）不缓存，下次打开就重新查，免得一次 429 卡住 60 秒
        if not info.error:
            with _cache_lock:
                _usage_cache[token] = (now, info)
    return info.model_copy(update={"token_id": entry["id"], "token_name": entry["name"]})


def _store_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except TokenStoreError as exc:
        raise ApiError(code=exc.code, message=exc.message, status_code=exc.status_code) from exc


def _login_failed_usage(exc: TokenStoreError) -> NovelAIUsageInfo:
    # 账号登录失败时照常返回一条带错误的用量，前端显示「失效」而不是整个请求报错
    return NovelAIUsageInfo(configured=True, error=exc.message)


@router.get("/novelai/usage", response_model=NovelAIUsageInfo)
def get_novelai_usage(request: Request) -> NovelAIUsageInfo:
    """获取当前生效 token 的会员状态与 V5 用量快照（带 60s 缓存）。"""
    try:
        entry = _store(request).active()
    except TokenStoreError as exc:
        return _login_failed_usage(exc)
    return _usage_for(request, entry, force_refresh=False)


@router.post("/novelai/usage/refresh", response_model=NovelAIUsageInfo)
def refresh_novelai_usage(request: Request) -> NovelAIUsageInfo:
    """强制重新向 NovelAI 官方查询当前 token 的会员状态与用量快照并更新缓存。"""
    try:
        entry = _store(request).active()
    except TokenStoreError as exc:
        return _login_failed_usage(exc)
    return _usage_for(request, entry, force_refresh=True)


class TokenCreateBody(BaseModel):
    name: str = ""
    token: str
    activate: bool = True


class TokenRenameBody(BaseModel):
    name: str


@router.get("/novelai/tokens")
def list_novelai_tokens(request: Request) -> dict[str, Any]:
    return _store(request).describe()


@router.post("/novelai/tokens")
def add_novelai_token(request: Request, body: TokenCreateBody) -> dict[str, Any]:
    store = _store(request)
    _store_call(store.add, body.name, body.token, activate=body.activate)
    return store.describe()


class TokenImportBody(BaseModel):
    text: str


@router.post("/novelai/tokens/import")
def import_novelai_tokens(request: Request, body: TokenImportBody) -> dict[str, Any]:
    """批量导入：每行一个 token（可写「名称 token」），已存在和同批重复的跳过。"""
    store = _store(request)
    result = store.import_lines(body.text)
    return {**store.describe(), **result}


@router.post("/novelai/tokens/import-accounts")
def import_novelai_accounts(request: Request, body: TokenImportBody) -> dict[str, Any]:
    """批量导入账号密码（每行「邮箱 密码」或旧 NAI_ACCOUNT 列表）。

    新账号加入后台登录队列后马上返回；已有的跳过，登录失败过的重新排队。
    """
    store = _store(request)
    result = store.import_accounts(body.text)
    return {**store.describe(), **result}


@router.post("/novelai/tokens/{token_id}/relogin")
def relogin_novelai_account(request: Request, token_id: str) -> dict[str, Any]:
    """把登录失败的账号放回后台登录队列。"""
    store = _store(request)
    _store_call(store.relogin, token_id)
    return store.describe()


@router.put("/novelai/tokens/{token_id}")
def rename_novelai_token(request: Request, token_id: str, body: TokenRenameBody) -> dict[str, Any]:
    store = _store(request)
    _store_call(store.rename, token_id, body.name)
    return store.describe()


@router.delete("/novelai/tokens/{token_id}")
def delete_novelai_token(request: Request, token_id: str) -> dict[str, Any]:
    store = _store(request)
    _store_call(store.remove, token_id)
    return store.describe()


@router.post("/novelai/tokens/{token_id}/activate")
def activate_novelai_token(request: Request, token_id: str) -> dict[str, Any]:
    store = _store(request)
    _store_call(store.activate, token_id)
    return store.describe()


@router.get("/novelai/tokens/{token_id}/usage", response_model=NovelAIUsageInfo)
def get_novelai_token_usage(request: Request, token_id: str, refresh: bool = False) -> NovelAIUsageInfo:
    """查任意一个已保存 token 的用量，用来在切换前比较各账号剩余额度。"""
    store = _store(request)
    try:
        # 不为排队中的账号临时登录，交给后台队列慢慢登
        entry = store.get(token_id, login=False)
    except TokenStoreError as exc:
        if exc.code not in ("novelai_login_failed", "novelai_login_pending"):
            raise ApiError(code=exc.code, message=exc.message, status_code=exc.status_code) from exc
        return _login_failed_usage(exc).model_copy(update={"token_id": token_id})
    return _usage_for(request, entry, force_refresh=refresh)
