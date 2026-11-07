"""NovelAI 账号密码登录，换取访问 token。

access key 算法和旧版 tags_machine/novelai 客户端一致：用户名和密码经 blake2b + argon2id 算出 access key，
POST /user/login 拿到 accessToken（JWT，会过期，过期前重新登录即可）。

旧客户端登录用 api.novelai.net，现在它对第三方请求一律返回
400 "Please refresh NovelAI.net. If using a third-party tool, update to the image URL."，
登录要改走 image.novelai.net（和查订阅一样）。
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from hashlib import blake2b
import json
import time
from typing import Any

import requests

from tags_machine_core.clients.novelai import IMAGE_BASE_URL, NOVELAI_WEB_HEADERS

LOGIN_BASE_URL = IMAGE_BASE_URL
LOGIN_PATH = "/user/login"
# JWT 里读不到过期时间时，按一天算，到期就重新登录
DEFAULT_TOKEN_LIFETIME_SECONDS = 24 * 3600


class NovelAILoginError(Exception):
    """登录失败。retryable=True 表示限流、服务器错误或网络问题，等一会儿重试可能成功。"""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    expires_at: float


def derive_access_key(username: str, password: str) -> str:
    """NovelAI 官网同款 access key：blake2b(密码前 6 位 + 用户名 + 固定串) 作盐，argon2id 哈希密码。"""
    import argon2  # 只有账号登录用到，延迟导入

    pre_salt = f"{password[:6]}{username}novelai_data_access_key"
    blake = blake2b(digest_size=16)
    blake.update(pre_salt.encode())
    raw = argon2.low_level.hash_secret_raw(
        secret=password.encode(),
        salt=blake.digest(),
        time_cost=2,
        memory_cost=int(2000000 / 1024),
        parallelism=1,
        hash_len=64,
        type=argon2.low_level.Type.ID,
    )
    return urlsafe_b64encode(raw).decode()[:64]


def token_expires_at(token: str, *, now: float | None = None) -> float:
    """读 JWT 的 exp；不是 JWT 或读不出来时按 DEFAULT_TOKEN_LIFETIME_SECONDS 估算。"""
    current = time.time() if now is None else now
    parts = token.split(".")
    if len(parts) == 3:
        try:
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            exp = json.loads(urlsafe_b64decode(payload)).get("exp")
            if isinstance(exp, (int, float)) and exp > 0:
                return float(exp)
        except (ValueError, json.JSONDecodeError):
            pass
    return current + DEFAULT_TOKEN_LIFETIME_SECONDS


def login_novelai(
    username: str,
    password: str,
    *,
    base_url: str = LOGIN_BASE_URL,
    session: Any | None = None,
    timeout: float = 30.0,
) -> LoginResult:
    key = derive_access_key(username, password)
    client = session or requests
    try:
        response = client.post(
            f"{base_url.rstrip('/')}{LOGIN_PATH}",
            json={"key": key},
            headers={**NOVELAI_WEB_HEADERS, "Content-Type": "application/json"},
            timeout=timeout,
        )
    except Exception as exc:  # 网络错误
        raise NovelAILoginError(f"连接失败: {exc}", retryable=True) from exc
    if response.status_code in (200, 201):
        token = (response.json() or {}).get("accessToken")
        if not token:
            raise NovelAILoginError("登录成功但没有返回 accessToken")
        return LoginResult(access_token=token, expires_at=token_expires_at(token))
    if response.status_code in (401, 403):
        raise NovelAILoginError(f"账号或密码错误 (HTTP {response.status_code})")
    if response.status_code == 400 and "refresh" in response.text.lower():
        raise NovelAILoginError(
            f"NovelAI 要求更新登录方式 (HTTP 400): {response.text[:160]}"
        )
    if response.status_code == 429:
        raise NovelAILoginError("登录太频繁被限流 (HTTP 429)", retryable=True)
    raise NovelAILoginError(
        f"登录失败 (HTTP {response.status_code}): {response.text[:120]}",
        retryable=response.status_code >= 500,
    )
