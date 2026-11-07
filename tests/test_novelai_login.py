from __future__ import annotations

from base64 import urlsafe_b64encode
import json
import unittest

from tags_machine_core.services.novelai_login import (
    DEFAULT_TOKEN_LIFETIME_SECONDS,
    NovelAILoginError,
    derive_access_key,
    login_novelai,
    token_expires_at,
)


def fake_jwt(exp: int) -> str:
    payload = urlsafe_b64encode(json.dumps({"id": "x", "exp": exp}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{payload}.sig"


class FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[dict] = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


class NovelAILoginTest(unittest.TestCase):
    def test_access_key_matches_legacy_client(self):
        # 和旧版 tags_machine/novelai/utils.py encode_access_key 对同一组假账号算出的结果一致
        self.assertEqual(
            derive_access_key("tester@example.com", "hunter2-fake-pw"),
            "KvIqz7KZBmpvKjLNqkEwP4tDRSvQyb5imJ2rv6fX_5Fenjcq_LVwr1fHGDoLvDd5",
        )

    def test_login_posts_key_and_reads_jwt_expiry(self):
        token = fake_jwt(2_000_000_000)
        session = FakeSession(FakeResponse(201, {"accessToken": token}))
        result = login_novelai("tester@example.com", "hunter2-fake-pw", session=session)

        self.assertEqual(result.access_token, token)
        self.assertEqual(result.expires_at, 2_000_000_000)
        call = session.calls[0]
        self.assertEqual(call["url"], "https://image.novelai.net/user/login")
        self.assertEqual(call["json"], {"key": derive_access_key("tester@example.com", "hunter2-fake-pw")})
        self.assertNotIn("hunter2-fake-pw", json.dumps(call["json"]))

    def test_login_errors(self):
        with self.assertRaisesRegex(NovelAILoginError, "账号或密码错误"):
            login_novelai("a@b.c", "x", session=FakeSession(FakeResponse(401)))
        with self.assertRaisesRegex(NovelAILoginError, "429"):
            login_novelai("a@b.c", "x", session=FakeSession(FakeResponse(429)))

    def test_non_jwt_token_gets_default_lifetime(self):
        self.assertEqual(
            token_expires_at("opaque", now=100.0), 100.0 + DEFAULT_TOKEN_LIFETIME_SECONDS
        )


if __name__ == "__main__":
    unittest.main()
