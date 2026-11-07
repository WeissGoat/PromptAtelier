from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tags_machine_core.config import load_config
from tags_machine_core.services.novelai_login import LoginResult, NovelAILoginError
from tags_machine_core.services.novelai_usage import NovelAIUsageInfo
from tags_machine_core.web.app import _with_active_novelai_token, create_app
from tags_machine_core.web.routes import novelai as novelai_route
from tags_machine_core.web.services.novelai_tokens import (
    CONFIG_TOKEN_ID,
    LOGIN_INTERVAL_SECONDS,
    RATE_LIMIT_BACKOFF_SECONDS,
    NovelAITokenStore,
    TokenStoreError,
)

CONFIG_TOKEN = "pst-config-token-aaaa1111"
SAVED_TOKEN = "pst-saved-token-bbbb2222"

LEGACY_ACCOUNTS = """NAI_ACCOUNT = [

    {
        "username" : "one@example.com",
        "password" : "pw-one"
    },
                {
        "username" : "two@example.com",
        "password" : "pw-two"
    },
    {
        "username" : "ONE@example.com",
        "password" : "pw-one-again"
    },
    {
        "username" : "bad@example.com",
        "password" : "wrong"
    },
]
"""


class FakeLogin:
    """假的登录：密码 wrong 失败；limited 前 n 次返回 429；其它返回 token-<邮箱>-<次数>。"""

    def __init__(self, clock, lifetime: float = 30 * 24 * 3600):
        self.clock = clock
        self.lifetime = lifetime
        self.calls: list[tuple[str, str]] = []
        self.rate_limited: dict[str, int] = {}

    def __call__(self, username: str, password: str) -> LoginResult:
        self.calls.append((username, password))
        if self.rate_limited.get(username, 0) > 0:
            self.rate_limited[username] -= 1
            raise NovelAILoginError("登录太频繁被限流 (HTTP 429)", retryable=True)
        if password == "wrong":
            raise NovelAILoginError("账号或密码错误 (HTTP 401)")
        count = sum(1 for name, _ in self.calls if name == username)
        return LoginResult(f"token-{username}-{count}", self.clock() + self.lifetime)


class NovelAIAccountImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1_000_000.0
        self.sleeps: list[float] = []
        self.login = FakeLogin(lambda: self.now)
        self.store = self.make_store()

    def make_store(self) -> NovelAITokenStore:
        return NovelAITokenStore(
            Path(self.tmp.name) / "tokens.json",
            config_token=lambda: CONFIG_TOKEN,
            login=self.login,
            clock=lambda: self.now,
            sleep=self.sleeps.append,
            background=False,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def statuses(self) -> dict[str, tuple[str | None, str | None]]:
        return {
            entry["account"]: (entry["login_status"], entry["login_error"])
            for entry in self.store.describe()["tokens"]
            if entry["kind"] == "account"
        }

    def test_import_queues_accounts_without_logging_in(self):
        result = self.store.import_accounts(LEGACY_ACCOUNTS)

        self.assertEqual(
            [entry["account"] for entry in result["added"]],
            ["one@example.com", "two@example.com", "bad@example.com"],
        )
        self.assertEqual(
            [(item["line"], item["reason"]) for item in result["skipped"]],
            [(12, "duplicate")],
        )
        self.assertEqual(self.login.calls, [])  # 导入时不登录
        self.assertEqual({status for status, _ in self.statuses().values()}, {"pending"})
        # 导入不切换；接口不返回密码
        self.assertEqual(self.store.active_token(), CONFIG_TOKEN)
        self.assertNotIn("pw-one", json.dumps(self.store.describe()))

    def test_queue_logs_in_one_by_one_with_interval(self):
        self.store.import_accounts(LEGACY_ACCOUNTS)

        self.assertEqual(self.store.process_login_queue(), 3)

        self.assertEqual(
            [name for name, _ in self.login.calls],
            ["one@example.com", "two@example.com", "bad@example.com"],
        )
        self.assertEqual(self.sleeps, [LOGIN_INTERVAL_SECONDS, LOGIN_INTERVAL_SECONDS])
        statuses = self.statuses()
        self.assertEqual(statuses["one@example.com"], ("ok", None))
        self.assertEqual(statuses["bad@example.com"][0], "failed")
        self.assertIn("HTTP 401", statuses["bad@example.com"][1])
        self.assertNotIn("token-one", json.dumps(self.store.describe()))

    def test_rate_limit_backs_off_and_retries(self):
        self.login.rate_limited["one@example.com"] = 2
        self.store.import_accounts("one@example.com pw-one")

        self.store.process_login_queue()

        self.assertEqual(len(self.login.calls), 3)
        self.assertEqual(self.sleeps, list(RATE_LIMIT_BACKOFF_SECONDS[:2]))
        self.assertEqual(self.statuses()["one@example.com"], ("ok", None))

    def test_rate_limit_gives_up_after_backoff_schedule(self):
        self.login.rate_limited["one@example.com"] = 99
        self.store.import_accounts("one@example.com pw-one")

        self.store.process_login_queue()

        self.assertEqual(len(self.login.calls), len(RATE_LIMIT_BACKOFF_SECONDS) + 1)
        status, error = self.statuses()["one@example.com"]
        self.assertEqual(status, "failed")
        self.assertIn("429", error)

    def test_reimport_skips_logged_in_and_requeues_failed(self):
        self.store.import_accounts(LEGACY_ACCOUNTS)
        self.store.process_login_queue()
        calls_before = len(self.login.calls)

        fixed = LEGACY_ACCOUNTS.replace('"wrong"', '"right-now"')
        again = self.store.import_accounts(fixed)

        self.assertEqual(again["added"], [])
        self.assertEqual([entry["account"] for entry in again["requeued"]], ["bad@example.com"])
        self.assertEqual(
            sorted(item["line"] for item in again["skipped"] if item["reason"] == "duplicate"),
            [4, 8, 12],
        )
        self.assertEqual(len(self.login.calls), calls_before)  # 导入本身不登录
        self.store.process_login_queue()
        # 只登录了重新排队的那个
        self.assertEqual(self.login.calls[calls_before:], [("bad@example.com", "right-now")])
        self.assertEqual(self.statuses()["bad@example.com"], ("ok", None))

    def test_relogin_puts_failed_account_back_in_queue(self):
        added = self.store.import_accounts("bad@example.com wrong")["added"][0]
        self.store.process_login_queue()
        self.assertEqual(self.statuses()["bad@example.com"][0], "failed")

        self.store.relogin(added["id"])
        self.assertEqual(self.statuses()["bad@example.com"], ("pending", None))
        with self.assertRaises(TokenStoreError):
            self.store.relogin(CONFIG_TOKEN_ID)

    def test_import_line_formats(self):
        text = "\n".join(
            [
                "# 注释",
                "a@example.com pw a",
                "b@example.com,pw-b",
                "c@example.com:pw:c",
                "d@example.com----pw-d",
                "only-email@example.com",
            ]
        )
        result = self.store.import_accounts(text)
        self.assertEqual(len(result["added"]), 4)
        self.assertEqual([(item["line"], item["reason"]) for item in result["skipped"]], [(6, "invalid")])
        self.store.process_login_queue()
        self.assertEqual(
            self.login.calls,
            [
                ("a@example.com", "pw a"),
                ("b@example.com", "pw-b"),
                ("c@example.com", "pw:c"),
                ("d@example.com", "pw-d"),
            ],
        )

    def test_usage_lookup_does_not_jump_the_queue(self):
        added = self.store.import_accounts("one@example.com pw-one")["added"][0]
        with self.assertRaises(TokenStoreError) as ctx:
            self.store.get(added["id"], login=False)
        self.assertEqual(ctx.exception.code, "novelai_login_pending")
        self.assertEqual(self.login.calls, [])

    def test_active_pending_account_logs_in_on_demand(self):
        added = self.store.import_accounts("one@example.com pw-one")["added"][0]
        self.store.activate(added["id"])
        # 出图要用时直接登录，不等队列
        self.assertEqual(self.store.active_token(), "token-one@example.com-1")
        self.assertEqual(self.statuses()["one@example.com"], ("ok", None))
        self.assertEqual(self.store.process_login_queue(), 0)

    def test_account_token_is_cached_and_relogged_before_expiry(self):
        added = self.store.import_accounts("one@example.com pw-one")["added"][0]
        self.store.process_login_queue()
        self.store.activate(added["id"])

        self.assertEqual(self.store.active_token(), "token-one@example.com-1")
        self.now += 29 * 24 * 3600  # 还剩一天，继续用缓存
        self.assertEqual(self.store.active_token(), "token-one@example.com-1")
        self.now += 23.5 * 3600  # 不到一小时过期，重新登录并保存
        self.assertEqual(self.store.active_token(), "token-one@example.com-2")
        self.assertEqual(self.make_store().active_token(), "token-one@example.com-2")
        self.assertEqual(len(self.login.calls), 2)

    def test_background_worker_drains_queue(self):
        store = NovelAITokenStore(
            Path(self.tmp.name) / "bg.json",
            config_token=lambda: None,
            login=self.login,
            sleep=lambda _seconds: None,
        )
        store.import_accounts("one@example.com pw-one\ntwo@example.com pw-two")
        deadline = time.time() + 5
        while time.time() < deadline:
            states = {entry["login_status"] for entry in store.describe()["tokens"]}
            if states == {"ok"} and store._worker is None:
                break
            time.sleep(0.02)
        self.assertEqual({entry["login_status"] for entry in store.describe()["tokens"]}, {"ok"})

    def test_account_routes(self):
        client = TestClient(create_app(novelai_token_store=self.store))
        response = client.post("/api/novelai/tokens/import-accounts", json={"text": LEGACY_ACCOUNTS})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["added"]), 3)
        self.assertEqual(len(data["tokens"]), 4)
        self.assertNotIn("pw-one", response.text)

        # 排队中的账号查用量：返回带说明的结果，不临时登录
        pending_id = data["added"][0]["id"]
        usage = client.get(f"/api/novelai/tokens/{pending_id}/usage")
        self.assertEqual(usage.status_code, 200)
        self.assertIn("排队", usage.json()["error"])
        self.assertEqual(self.login.calls, [])

        self.store.process_login_queue()
        bad_id = data["added"][2]["id"]
        failed = client.get(f"/api/novelai/tokens/{bad_id}/usage")
        self.assertIn("登录失败", failed.json()["error"])

        relogin = client.post(f"/api/novelai/tokens/{bad_id}/relogin")
        self.assertEqual(relogin.status_code, 200)
        bad = next(entry for entry in relogin.json()["tokens"] if entry["id"] == bad_id)
        self.assertEqual(bad["login_status"], "pending")


class NovelAITokenStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "tokens.json"
        self.config_token: str | None = CONFIG_TOKEN
        self.store = NovelAITokenStore(self.path, config_token=lambda: self.config_token)

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_token_is_default_and_listed_masked(self):
        data = self.store.describe()
        self.assertEqual(data["active_id"], CONFIG_TOKEN_ID)
        self.assertEqual(len(data["tokens"]), 1)
        entry = data["tokens"][0]
        self.assertEqual(entry["source"], "config")
        self.assertEqual(entry["token_masked"], "pst-...1111")
        self.assertNotIn(CONFIG_TOKEN, json.dumps(data))
        self.assertEqual(self.store.active_token(), CONFIG_TOKEN)

    def test_add_activates_and_persists(self):
        entry = self.store.add("小号", f"Bearer {SAVED_TOKEN}\n")
        self.assertTrue(entry["active"])
        self.assertEqual(self.store.active_token(), SAVED_TOKEN)

        reloaded = NovelAITokenStore(self.path, config_token=lambda: CONFIG_TOKEN)
        self.assertEqual(reloaded.active_token(), SAVED_TOKEN)
        names = [item["name"] for item in reloaded.describe()["tokens"]]
        self.assertEqual(names, ["配置文件", "小号"])

    def test_add_without_activate_keeps_current(self):
        self.store.add("小号", SAVED_TOKEN, activate=False)
        self.assertEqual(self.store.active_token(), CONFIG_TOKEN)

    def test_add_rejects_duplicates_and_empty(self):
        with self.assertRaises(TokenStoreError) as ctx:
            self.store.add("重复", CONFIG_TOKEN)
        self.assertEqual(ctx.exception.status_code, 409)
        with self.assertRaises(TokenStoreError):
            self.store.add("空", "   ")
        with self.assertRaises(TokenStoreError):
            self.store.add("空格", "abc def")

    def test_rename_saved_and_config(self):
        entry = self.store.add("a", SAVED_TOKEN)
        self.store.rename(entry["id"], "主力号")
        self.store.rename(CONFIG_TOKEN_ID, "本地配置")
        names = [item["name"] for item in self.store.describe()["tokens"]]
        self.assertEqual(names, ["本地配置", "主力号"])
        with self.assertRaises(TokenStoreError):
            self.store.rename(entry["id"], "  ")

    def test_remove_active_falls_back_to_config(self):
        entry = self.store.add("a", SAVED_TOKEN)
        self.store.remove(entry["id"])
        self.assertEqual(self.store.active_token(), CONFIG_TOKEN)
        with self.assertRaises(TokenStoreError):
            self.store.remove(CONFIG_TOKEN_ID)

    def test_without_config_token_first_saved_becomes_active(self):
        self.config_token = None
        self.assertIsNone(self.store.active_token())
        self.store.add("a", SAVED_TOKEN, activate=False)
        self.assertEqual(self.store.active_token(), SAVED_TOKEN)
        with self.assertRaises(TokenStoreError):
            self.store.activate(CONFIG_TOKEN_ID)

    def test_switch_between_tokens(self):
        entry = self.store.add("a", SAVED_TOKEN)
        self.store.activate(CONFIG_TOKEN_ID)
        self.assertEqual(self.store.active_token(), CONFIG_TOKEN)
        self.store.activate(entry["id"])
        self.assertEqual(self.store.active_token(), SAVED_TOKEN)


class NovelAITokenImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = NovelAITokenStore(
            Path(self.tmp.name) / "tokens.json", config_token=lambda: CONFIG_TOKEN
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_account_list_pasted_as_tokens_is_imported_as_accounts(self):
        store = NovelAITokenStore(
            Path(self.tmp.name) / "routed.json",
            config_token=lambda: CONFIG_TOKEN,
            login=FakeLogin(time.time),
            background=False,
        )
        result = store.import_lines(LEGACY_ACCOUNTS)

        self.assertEqual(result["imported_as"], "accounts")
        self.assertEqual(
            [entry["account"] for entry in result["added"]],
            ["one@example.com", "two@example.com", "bad@example.com"],
        )
        saved = store.describe()["tokens"]
        self.assertEqual({entry["kind"] for entry in saved if entry["source"] == "saved"}, {"account"})
        # 密码不会被当成 token 存下来
        raw = json.loads(store.path.read_text(encoding="utf-8"))
        self.assertTrue(all(item["kind"] == "account" for item in raw["tokens"]))

    def test_non_token_lines_are_rejected(self):
        text = "\n".join(
            [
                "[",
                "{",
                '"password" : "hunter2",',
                "},",
                "some-password",
                "pst-real-looking-token-1111",
                "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjF9.sig",
            ]
        )
        result = self.store.import_lines(text)

        self.assertEqual(len(result["added"]), 2)
        self.assertEqual(
            [(item["line"], item["reason"]) for item in result["skipped"]],
            [(1, "invalid"), (2, "invalid"), (3, "invalid"), (4, "invalid"), (5, "invalid")],
        )
        self.assertIn("pst-", result["skipped"][0]["message"])
        with self.assertRaises(TokenStoreError):
            self.store.add("密码", "hunter2")

    def test_import_dedupes_against_saved_and_within_batch(self):
        self.store.add("老号", SAVED_TOKEN, activate=False)
        text = "\n".join(
            [
                "# 注释行",
                "pst-new-one-1111",
                "",
                "  pst-new-one-1111  ",  # 同批重复
                SAVED_TOKEN,  # 已保存
                CONFIG_TOKEN,  # 配置文件里的
                "Bearer pst-new-two-2222",
                "主力号 pst-new-three-3333",
                "备用,pst-new-four-4444",
                "Bearer pst-new-two-2222",  # 去掉 Bearer 后重复
            ]
        )
        result = self.store.import_lines(text)

        self.assertEqual(
            [entry["name"] for entry in result["added"]],
            ["Token pst-...1111", "Token pst-...2222", "主力号", "备用"],
        )
        self.assertEqual(
            [(item["line"], item["reason"]) for item in result["skipped"]],
            [(4, "duplicate"), (5, "duplicate"), (6, "duplicate"), (10, "duplicate")],
        )
        # 导入不切换当前 token
        self.assertEqual(self.store.active_token(), CONFIG_TOKEN)
        self.assertEqual(len(self.store.describe()["tokens"]), 6)

        again = self.store.import_lines(text)
        self.assertEqual(again["added"], [])
        self.assertEqual(len(self.store.describe()["tokens"]), 6)

    def test_import_into_empty_store_activates_first(self):
        store = NovelAITokenStore(Path(self.tmp.name) / "empty.json", config_token=lambda: None)
        store.import_lines("pst-a-1111\npst-b-2222")
        self.assertEqual(store.active_token(), "pst-a-1111")


class ActiveTokenConfigTest(unittest.TestCase):
    def test_executor_config_uses_active_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = load_config("configs/local.example.yaml")
            config = base.model_copy(
                update={"novelai": base.novelai.model_copy(update={"access_token": CONFIG_TOKEN})}
            )
            store = NovelAITokenStore(Path(tmp) / "t.json", config_token=lambda: CONFIG_TOKEN)
            self.assertIs(_with_active_novelai_token(config, store), config)
            store.add("a", SAVED_TOKEN)
            updated = _with_active_novelai_token(config, store)
            self.assertEqual(updated.novelai.access_token, SAVED_TOKEN)
            self.assertEqual(config.novelai.access_token, CONFIG_TOKEN)


class NovelAITokenRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = NovelAITokenStore(
            Path(self.tmp.name) / "tokens.json", config_token=lambda: CONFIG_TOKEN
        )
        self.client = TestClient(create_app(novelai_token_store=store))
        novelai_route._usage_cache.clear()

    def tearDown(self):
        self.tmp.cleanup()
        novelai_route._usage_cache.clear()

    def test_crud_flow(self):
        response = self.client.post(
            "/api/novelai/tokens", json={"name": "小号", "token": SAVED_TOKEN}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        saved = next(item for item in data["tokens"] if item["source"] == "saved")
        self.assertEqual(data["active_id"], saved["id"])
        self.assertNotIn(SAVED_TOKEN, response.text)

        duplicate = self.client.post("/api/novelai/tokens", json={"token": SAVED_TOKEN})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "novelai_token_duplicate")

        renamed = self.client.put(f"/api/novelai/tokens/{saved['id']}", json={"name": "主力"})
        self.assertEqual(renamed.json()["tokens"][1]["name"], "主力")

        switched = self.client.post(f"/api/novelai/tokens/{CONFIG_TOKEN_ID}/activate")
        self.assertEqual(switched.json()["active_id"], CONFIG_TOKEN_ID)

        deleted = self.client.delete(f"/api/novelai/tokens/{saved['id']}")
        self.assertEqual(len(deleted.json()["tokens"]), 1)
        self.assertEqual(self.client.delete("/api/novelai/tokens/missing").status_code, 404)

    @patch("tags_machine_core.web.routes.novelai.inquire_novelai_usage")
    def test_per_token_usage_cache_and_refresh(self, mock_inquire):
        mock_inquire.side_effect = lambda token, **_: NovelAIUsageInfo(
            token_masked=token[-4:], active=True, tier=3, anlas=100
        )
        imported = self.client.post("/api/novelai/tokens/import", json={"text": SAVED_TOKEN})
        saved_id = imported.json()["added"][0]["id"]

        response = self.client.get(f"/api/novelai/tokens/{saved_id}/usage")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["anlas"], 100)
        self.assertNotIn(SAVED_TOKEN, response.text)
        self.assertEqual(mock_inquire.call_args.args[0], SAVED_TOKEN)
        self.assertEqual(mock_inquire.call_count, 1)

        # 走缓存；refresh=true 才重新查
        self.client.get(f"/api/novelai/tokens/{saved_id}/usage")
        self.assertEqual(mock_inquire.call_count, 1)
        self.client.get(f"/api/novelai/tokens/{saved_id}/usage?refresh=true")
        self.assertEqual(mock_inquire.call_count, 2)
        self.assertEqual(self.client.get("/api/novelai/tokens/missing/usage").status_code, 404)

    def test_import_route(self):
        response = self.client.post(
            "/api/novelai/tokens/import",
            json={"text": f"{SAVED_TOKEN}\n{SAVED_TOKEN}\n{CONFIG_TOKEN}\n"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["added"]), 1)
        self.assertEqual(len(data["skipped"]), 2)
        self.assertEqual(len(data["tokens"]), 2)
        self.assertEqual(data["active_id"], CONFIG_TOKEN_ID)
        self.assertNotIn(SAVED_TOKEN, response.text)

    @patch("tags_machine_core.web.routes.novelai.inquire_novelai_usage")
    def test_failed_usage_is_not_cached(self, mock_inquire):
        mock_inquire.return_value = NovelAIUsageInfo(error="NovelAI 请求失败 (HTTP 429)")
        self.client.get(f"/api/novelai/tokens/{CONFIG_TOKEN_ID}/usage")
        self.client.get(f"/api/novelai/tokens/{CONFIG_TOKEN_ID}/usage")
        self.assertEqual(mock_inquire.call_count, 2)

        mock_inquire.return_value = NovelAIUsageInfo(active=True, tier=3)
        self.client.get(f"/api/novelai/tokens/{CONFIG_TOKEN_ID}/usage")
        self.client.get(f"/api/novelai/tokens/{CONFIG_TOKEN_ID}/usage")
        self.assertEqual(mock_inquire.call_count, 3)

    @patch("tags_machine_core.web.routes.novelai.inquire_novelai_usage")
    def test_usage_follows_active_token(self, mock_inquire):
        mock_inquire.side_effect = lambda token, **_: NovelAIUsageInfo(
            token_masked=token[-4:], active=True, tier=3, usage_percent=50.0
        )
        first = self.client.get("/api/novelai/usage").json()
        self.assertEqual(first["token_id"], CONFIG_TOKEN_ID)
        self.assertEqual(first["token_name"], "配置文件")

        self.client.post("/api/novelai/tokens", json={"name": "小号", "token": SAVED_TOKEN})
        second = self.client.get("/api/novelai/usage").json()
        self.assertEqual(second["token_name"], "小号")
        self.assertEqual(mock_inquire.call_args.args[0], SAVED_TOKEN)

        # 各 token 单独缓存：切回配置 token 不再请求
        calls = mock_inquire.call_count
        per_token = self.client.get(f"/api/novelai/tokens/{CONFIG_TOKEN_ID}/usage").json()
        self.assertEqual(per_token["token_name"], "配置文件")
        self.assertEqual(mock_inquire.call_count, calls)


if __name__ == "__main__":
    unittest.main()
