from __future__ import annotations

from collections.abc import Callable
import json
import re
from pathlib import Path
import threading
import time
from typing import Any
import uuid

from tags_machine_core.services.novelai_login import (
    LoginResult,
    NovelAILoginError,
    login_novelai,
)
from tags_machine_core.services.novelai_usage import mask_token


CONFIG_TOKEN_ID = "config"
DEFAULT_CONFIG_TOKEN_NAME = "配置文件"
STORE_SCHEMA = "tags-machine-core.web.novelai-tokens/v1"
MAX_NAME_LENGTH = 40
# 账号登录拿到的 token 离过期不到这么久就重新登录
TOKEN_REFRESH_MARGIN_SECONDS = 3600
# 后台登录队列：一个接一个登录，每两个账号之间停一会儿；被限流就越等越久再试
LOGIN_INTERVAL_SECONDS = 3.0
RATE_LIMIT_BACKOFF_SECONDS = (30, 60, 120, 240, 480)


class TokenStoreError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class NovelAITokenStore:
    """Web 里管理的多个 NovelAI token，以及当前出图用哪一个。

    配置文件（或环境变量）里的 token 作为固定的一项 ``config`` 出现，可以改名但不能删；
    网页添加的 token 存在 JSON 文件里。接口只返回脱敏后的 token。

    记录分两种：``kind="token"`` 直接保存 token（pst-…）；``kind="account"`` 保存账号密码，
    用时登录换 token 并缓存，快过期时自动重新登录（和旧版 NAI_ACCOUNT 的用法一样）。

    批量导入的账号先存成 ``login_status="pending"``，由后台线程逐个登录（见 process_login_queue），
    成功变 ``ok``，账号密码错误变 ``failed``；限流和网络错误等一会儿自动重试。
    """

    def __init__(
        self,
        path: str | Path,
        *,
        config_token: Callable[[], str | None],
        login: Callable[[str, str], LoginResult] = login_novelai,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        background: bool = True,
    ):
        self.path = Path(path)
        self._config_token = config_token
        self._login = login
        self._clock = clock
        self._sleep = sleep
        # False 时不起后台线程，由调用方（测试）自己调 process_login_queue()
        self._background = background
        self._lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._kicked = False

    # ---- 读 ----

    def describe(self) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            active_id = self._resolve_active_id(data)
            return {
                "schema": STORE_SCHEMA,
                "active_id": active_id,
                "tokens": [
                    self._public(entry, active_id) for entry in self._entries(data)
                ],
            }

    def active(self) -> dict[str, Any] | None:
        """当前生效的 token 记录（含明文 token），没有可用 token 时返回 None。

        账号记录会在需要时登录换 token；登录失败抛 TokenStoreError。
        """
        with self._lock:
            data = self._load()
            active_id = self._resolve_active_id(data)
            found = next(
                (dict(entry) for entry in self._entries(data) if entry["id"] == active_id), None
            )
        return self._ensure_token(found) if found else None

    def active_token(self) -> str | None:
        entry = self.active()
        return entry["token"] if entry else None

    def get(self, token_id: str, *, login: bool = True) -> dict[str, Any]:
        """login=False 时不为还在排队或登录失败的账号临时登录（查用量用，避免绕过后台队列）。"""
        with self._lock:
            entry = dict(self._find(self._load(), token_id))
        return self._ensure_token(entry, allow_login=login)


    # ---- 写 ----

    def add(self, name: str, token: str, *, activate: bool = True) -> dict[str, Any]:
        clean_token = _clean_token(token)
        clean_name = _clean_name(name) or f"Token {mask_token(clean_token)}"
        with self._lock:
            data = self._load()
            for entry in self._entries(data):
                if entry.get("token") and entry["token"] == clean_token:
                    raise TokenStoreError(
                        "novelai_token_duplicate",
                        f"这个 token 已经添加过了（{entry['name']}）",
                        409,
                    )
            entry = {
                "id": uuid.uuid4().hex[:12],
                "kind": "token",
                "name": clean_name,
                "token": clean_token,
                "created_at": time.time(),
            }
            data["tokens"].append(entry)
            if activate or self._resolve_active_id(data) == entry["id"]:
                data["active_id"] = entry["id"]
            self._save(data)
            return self._public(entry, self._resolve_active_id(data))

    def import_lines(self, text: str) -> dict[str, Any]:
        """批量导入，每行一个 token；行内可以在 token 前写名称（「主力号 pst-xxx」）。

        空行和 # 开头的行忽略。已经保存过的、同一批里重复的都跳过，不会切换当前 token。
        粘贴的是账号密码列表（含 "username": … "password": …）时按账号导入，免得把密码当 token 存。
        """
        if _ACCOUNT_PAIR.search(str(text or "")):
            return {**self.import_accounts(text), "imported_as": "accounts"}
        added: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        with self._lock:
            data = self._load()
            existing = {
                entry["token"]: entry["name"]
                for entry in self._entries(data)
                if entry.get("token")
            }
            for line_no, raw_line in enumerate(str(text or "").splitlines(), start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                name, token_text = _split_import_line(line)
                try:
                    clean_token = _clean_token(token_text)
                except TokenStoreError as exc:
                    skipped.append({"line": line_no, "reason": "invalid", "message": exc.message})
                    continue
                if clean_token in existing:
                    skipped.append(
                        {
                            "line": line_no,
                            "reason": "duplicate",
                            "message": f"已存在（{existing[clean_token]}）",
                        }
                    )
                    continue
                entry = {
                    "id": uuid.uuid4().hex[:12],
                    "kind": "token",
                    "name": _clean_name(name) or f"Token {mask_token(clean_token)}",
                    "token": clean_token,
                    "created_at": time.time(),
                }
                data["tokens"].append(entry)
                existing[clean_token] = entry["name"]
                added.append(entry)
            if added:
                self._save(data)
            active_id = self._resolve_active_id(data)
            return {
                "added": [self._public(entry, active_id) for entry in added],
                "skipped": skipped,
            }

    def import_accounts(self, text: str) -> dict[str, Any]:
        """批量导入账号密码：每行「邮箱 密码」（也可用 , | : 或 ---- 分隔），
        或者直接粘贴旧 nai_const.py 里的 NAI_ACCOUNT 列表。

        新账号立即保存为「排队登录」，后台线程逐个登录，接口马上返回。
        已有的账号（邮箱不分大小写）跳过、不会重新登录；之前登录失败的账号用新密码重新排队。
        """
        added: list[dict[str, Any]] = []
        requeued: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        with self._lock:
            data = self._load()
            existing = {
                entry["username"].lower(): entry
                for entry in data["tokens"]
                if entry.get("kind") == "account"
            }
            seen: set[str] = set()
            for line_no, username, password in _parse_accounts(text):
                if not username or not password:
                    skipped.append({"line": line_no, "reason": "invalid", "message": "需要邮箱和密码"})
                    continue
                key = username.lower()
                if key in seen:
                    skipped.append({"line": line_no, "reason": "duplicate", "message": "同一批里重复"})
                    continue
                seen.add(key)
                current = existing.get(key)
                if current is not None and current.get("login_status") == "failed":
                    current.update(password=password, login_status="pending", login_error=None)
                    requeued.append(current)
                    continue
                if current is not None:
                    skipped.append(
                        {"line": line_no, "reason": "duplicate", "message": f"已存在（{current['name']}）"}
                    )
                    continue
                entry = {
                    "id": uuid.uuid4().hex[:12],
                    "kind": "account",
                    "name": _clean_name(username),
                    "username": username,
                    "password": password,
                    "token": "",
                    "token_expires_at": None,
                    "login_status": "pending",
                    "login_error": None,
                    "created_at": time.time(),
                }
                data["tokens"].append(entry)
                existing[key] = entry
                added.append(entry)
            if added or requeued:
                self._save(data)
            active_id = self._resolve_active_id(data)
        if added or requeued:
            self.kick_login_queue()
        return {
            "added": [self._public(entry, active_id) for entry in added],
            "requeued": [self._public(entry, active_id) for entry in requeued],
            "skipped": skipped,
        }

    def relogin(self, token_id: str) -> dict[str, Any]:
        """把账号放回后台登录队列（登录失败后重试）。"""
        with self._lock:
            data = self._load()
            entry = self._find_saved(data, token_id)
            if entry.get("kind") != "account":
                raise TokenStoreError("novelai_token_not_account", "只有账号密码登录的记录能重新登录")
            entry.update(login_status="pending", login_error=None)
            self._save(data)
            public = self._public(entry, self._resolve_active_id(data))
        self.kick_login_queue()
        return public

    # ---- 后台登录队列 ----

    def kick_login_queue(self) -> None:
        """有排队的账号就确保后台线程在跑；background=False 时什么也不做。"""
        if not self._background:
            return
        with self._worker_lock:
            self._kicked = True
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._worker_loop, name="novelai-login-queue", daemon=True
                )
                self._worker.start()

    def _worker_loop(self) -> None:
        while True:
            with self._worker_lock:
                self._kicked = False
            try:
                self.process_login_queue()
            except Exception:  # 后台线程不能因为一个意外退出后把队列卡住
                self._sleep(LOGIN_INTERVAL_SECONDS)
            with self._worker_lock:
                if not self._kicked:
                    self._worker = None
                    return

    def process_login_queue(self) -> int:
        """按导入顺序逐个登录排队的账号，直到队列空。返回本次处理的账号数。"""
        processed = 0
        while True:
            with self._lock:
                pending = [
                    entry
                    for entry in self._load()["tokens"]
                    if entry.get("kind") == "account" and entry.get("login_status") == "pending"
                ]
            if not pending:
                return processed
            if processed:
                self._sleep(LOGIN_INTERVAL_SECONDS)
            entry = min(pending, key=lambda item: item.get("created_at") or 0)
            self._login_with_backoff(entry)
            processed += 1

    def _login_with_backoff(self, entry: dict[str, Any]) -> None:
        for attempt in range(len(RATE_LIMIT_BACKOFF_SECONDS) + 1):
            try:
                result = self._login(entry["username"], entry["password"])
            except NovelAILoginError as exc:
                if exc.retryable and attempt < len(RATE_LIMIT_BACKOFF_SECONDS):
                    wait = RATE_LIMIT_BACKOFF_SECONDS[attempt]
                    if not self._update_account(
                        entry["id"], login_error=f"{exc}，{wait} 秒后重试"
                    ):
                        return  # 等待期间被删了
                    self._sleep(wait)
                    continue
                self._update_account(entry["id"], login_status="failed", login_error=str(exc))
                return
            self._update_account(
                entry["id"],
                token=result.access_token,
                token_expires_at=result.expires_at,
                login_status="ok",
                login_error=None,
            )
            return

    def _update_account(self, token_id: str, **fields: Any) -> bool:
        with self._lock:
            data = self._load()
            for stored in data["tokens"]:
                if stored["id"] == token_id:
                    stored.update(fields)
                    self._save(data)
                    return True
        return False

    def rename(self, token_id: str, name: str) -> dict[str, Any]:
        clean_name = _clean_name(name)
        if not clean_name:
            raise TokenStoreError("novelai_token_name_required", "名称不能为空")
        with self._lock:
            data = self._load()
            if token_id == CONFIG_TOKEN_ID:
                entry = self._find(data, token_id)
                data["config_name"] = clean_name
                entry["name"] = clean_name
            else:
                entry = self._find_saved(data, token_id)
                entry["name"] = clean_name
            self._save(data)
            return self._public(entry, self._resolve_active_id(data))

    def remove(self, token_id: str) -> None:
        if token_id == CONFIG_TOKEN_ID:
            raise TokenStoreError(
                "novelai_token_readonly",
                "配置文件里的 token 不能在网页删除，请修改 configs/local.yaml",
            )
        with self._lock:
            data = self._load()
            entry = self._find_saved(data, token_id)
            data["tokens"] = [item for item in data["tokens"] if item is not entry]
            if data.get("active_id") == token_id:
                data["active_id"] = None
            self._save(data)

    def activate(self, token_id: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            entry = self._find(data, token_id)
            data["active_id"] = token_id
            self._save(data)
            return self._public(entry, token_id)

    # ---- 内部 ----

    def _ensure_token(self, entry: dict[str, Any], *, allow_login: bool = True) -> dict[str, Any]:
        """账号记录没有 token 或快过期时登录一次，把新 token 存回去。

        allow_login=False 时，还在排队或登录失败的账号直接报错，不临时登录。
        """
        if entry.get("kind") != "account":
            return entry
        expires_at = float(entry.get("token_expires_at") or 0)
        if entry.get("token") and expires_at - self._clock() > TOKEN_REFRESH_MARGIN_SECONDS:
            return entry
        status = entry.get("login_status")
        if not allow_login and status == "pending":
            raise TokenStoreError(
                "novelai_login_pending", entry.get("login_error") or "排队等待登录", 409
            )
        if not allow_login and status == "failed":
            raise TokenStoreError(
                "novelai_login_failed", f"登录失败：{entry.get('login_error') or ''}", 502
            )
        try:
            result = self._login(entry["username"], entry["password"])
        except NovelAILoginError as exc:
            if not exc.retryable:
                self._update_account(entry["id"], login_status="failed", login_error=str(exc))
            raise TokenStoreError(
                "novelai_login_failed", f"{entry['username']} 登录失败：{exc}", 502
            ) from exc
        self._update_account(
            entry["id"],
            token=result.access_token,
            token_expires_at=result.expires_at,
            login_status="ok",
            login_error=None,
        )
        return {
            **entry,
            "token": result.access_token,
            "token_expires_at": result.expires_at,
            "login_status": "ok",
            "login_error": None,
        }

    def _entries(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        config_token = (self._config_token() or "").strip()
        if config_token:
            entries.append(
                {
                    "id": CONFIG_TOKEN_ID,
                    "name": data.get("config_name") or DEFAULT_CONFIG_TOKEN_NAME,
                    "token": config_token,
                    "source": "config",
                    "created_at": None,
                }
            )
        for entry in data["tokens"]:
            entries.append({**entry, "source": "saved"})
        return entries

    def _resolve_active_id(self, data: dict[str, Any]) -> str | None:
        entries = self._entries(data)
        ids = [entry["id"] for entry in entries]
        active_id = data.get("active_id")
        if active_id in ids:
            return active_id
        # 没选或选中的被删了：优先配置文件，否则第一个已保存的
        return ids[0] if ids else None

    def _find(self, data: dict[str, Any], token_id: str) -> dict[str, Any]:
        if token_id == CONFIG_TOKEN_ID:
            for entry in self._entries(data):
                if entry["id"] == CONFIG_TOKEN_ID:
                    return entry
            raise TokenStoreError(
                "novelai_token_not_found", "配置文件里没有设置 NovelAI token", 404
            )
        return self._find_saved(data, token_id)

    def _find_saved(self, data: dict[str, Any], token_id: str) -> dict[str, Any]:
        for entry in data["tokens"]:
            if entry["id"] == token_id:
                return entry
        raise TokenStoreError("novelai_token_not_found", f"找不到 token：{token_id}", 404)

    @staticmethod
    def _public(entry: dict[str, Any], active_id: str | None) -> dict[str, Any]:
        is_account = entry.get("kind") == "account"
        return {
            "id": entry["id"],
            "name": entry["name"],
            "kind": "account" if is_account else "token",
            # 账号记录不显示 token（会定期换），显示邮箱
            "token_masked": "" if is_account else mask_token(entry.get("token")),
            "account": entry.get("username") if is_account else None,
            # 账号：pending 排队登录 / ok 已登录 / failed 登录失败（login_error 是原因）
            "login_status": entry.get("login_status") if is_account else None,
            "login_error": entry.get("login_error") if is_account else None,
            "source": entry.get("source", "saved"),
            "active": entry["id"] == active_id,
            "created_at": entry.get("created_at"),
        }

    def _load(self) -> dict[str, Any]:
        empty: dict[str, Any] = {"active_id": None, "config_name": None, "tokens": []}
        if not self.path.is_file():
            return empty
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return empty
        if not isinstance(raw, dict):
            return empty
        tokens: list[dict[str, Any]] = []
        for item in raw.get("tokens") or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            if item.get("kind") == "account":
                if not item.get("username") or not item.get("password"):
                    continue
                tokens.append(
                    {
                        "id": str(item["id"]),
                        "kind": "account",
                        "name": str(item.get("name") or item["username"]),
                        "username": str(item["username"]),
                        "password": str(item["password"]),
                        "token": str(item.get("token") or ""),
                        "token_expires_at": item.get("token_expires_at"),
                        "login_status": item.get("login_status")
                        or ("ok" if item.get("token") else "pending"),
                        "login_error": item.get("login_error"),
                        "created_at": item.get("created_at"),
                    }
                )
            elif item.get("token"):
                tokens.append(
                    {
                        "id": str(item["id"]),
                        "kind": "token",
                        "name": str(item.get("name") or ""),
                        "token": str(item["token"]),
                        "created_at": item.get("created_at"),
                    }
                )
        return {
            "active_id": raw.get("active_id"),
            "config_name": raw.get("config_name"),
            "tokens": tokens,
        }

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": STORE_SCHEMA,
            "active_id": data.get("active_id"),
            "config_name": data.get("config_name"),
            "tokens": data["tokens"],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def _clean_token(token: str) -> str:
    text = str(token or "").strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    if not text:
        raise TokenStoreError("novelai_token_required", "token 不能为空")
    if any(ch.isspace() for ch in text):
        raise TokenStoreError("novelai_token_invalid", "token 里不能有空格或换行")
    if not looks_like_novelai_token(text):
        raise TokenStoreError(
            "novelai_token_invalid",
            "不像 NovelAI token（应以 pst- 开头）；账号密码请用「账号密码」导入",
        )
    return text


_JWT = re.compile(r"^[\w-]+\.[\w-]+\.[\w-]+$")


def looks_like_novelai_token(text: str) -> bool:
    """NovelAI 的 token 只有两种：Persistent API Token（pst-…）和登录拿到的 JWT。"""
    return (text.startswith("pst-") and len(text) > 8) or bool(_JWT.match(text))


def _split_import_line(line: str) -> tuple[str, str]:
    """「名称 token」拆成两段：token 里没有空白和分隔符，所以最后一段是 token，前面是名称。

    「Bearer pst-xxx」整行当作 token，由 _clean_token 去掉前缀。
    """
    match = re.match(r"^(.*?)[\s,，|:：]+(\S+)$", line)
    if match is None or match.group(1).strip().lower() == "bearer":
        return "", line
    return match.group(1).strip(), match.group(2)


_ACCOUNT_PAIR = re.compile(
    r"""["']username["']\s*:\s*["']([^"']*)["']\s*,\s*["']password["']\s*:\s*["']([^"']*)["']""",
    re.S,
)
_ACCOUNT_LINE = re.compile(r"^([^\s,，|:：]+)\s*(?:----|[\s,，|:：])\s*(.*)$")


def _parse_accounts(text: str) -> list[tuple[int, str, str]]:
    """解析账号文本，返回 (行号, 邮箱, 密码)。

    含 "username": … "password": … 的文本（旧 NAI_ACCOUNT 列表、JSON）按键值对提取，
    否则每行一个「邮箱 密码」。
    """
    raw = str(text or "")
    pairs = list(_ACCOUNT_PAIR.finditer(raw))
    if pairs:
        return [
            (raw.count("\n", 0, match.start()) + 1, match.group(1).strip(), match.group(2))
            for match in pairs
        ]
    accounts: list[tuple[int, str, str]] = []
    for line_no, raw_line in enumerate(raw.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ACCOUNT_LINE.match(line)
        if match is None:
            accounts.append((line_no, line, ""))
        else:
            accounts.append((line_no, match.group(1), match.group(2).strip()))
    return accounts


def _clean_name(name: str | None) -> str:
    return str(name or "").strip()[:MAX_NAME_LENGTH]
