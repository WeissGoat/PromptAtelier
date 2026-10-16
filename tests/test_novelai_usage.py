from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tags_machine_core.services.novelai_usage import (
    NovelAIUsageInfo,
    format_usage_summary,
    inquire_novelai_usage,
    mask_token,
)


class FakeResponse:
    def __init__(self, status_code: int, data: dict | None = None, text: str = "OK"):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


class TestNovelAIUsage(unittest.TestCase):
    def test_mask_token(self):
        self.assertEqual(mask_token(None), "")
        self.assertEqual(mask_token(""), "")
        self.assertEqual(mask_token("short"), "***")
        self.assertEqual(mask_token("pst-12345678abcdef"), "pst-...cdef")

    def test_inquire_unconfigured_token(self):
        info = inquire_novelai_usage(None)
        self.assertFalse(info.configured)
        self.assertIn("未配置", info.error)
        self.assertFalse(info.active)

    def test_inquire_success_opus_tier(self):
        fake_data = {
            "active": True,
            "tier": 3,
            "trainingStepsLeft": {
                "fixedTrainingStepsLeft": 10000,
                "purchasedTrainingSteps": 2500,
            },
            "usage": {
                "percent": 87.5,
                "timeUntilNextPercent": 142.0,
            },
        }
        mock_session = MagicMock()
        mock_session.get.return_value = FakeResponse(200, fake_data)

        info = inquire_novelai_usage("pst-valid-token-secret-1234", session=mock_session)

        self.assertTrue(info.configured)
        self.assertTrue(info.active)
        self.assertEqual(info.tier, 3)
        self.assertEqual(info.tier_name, "Opus")
        self.assertEqual(info.anlas, 10000)
        self.assertEqual(info.fixed_anlas, 10000)
        self.assertEqual(info.purchased_anlas, 2500)
        self.assertEqual(info.usage_percent, 87.5)
        self.assertEqual(info.time_until_next_percent, 142.0)
        self.assertTrue(info.unlimited_v5_eligible)
        self.assertIsNone(info.error)

    def test_inquire_success_purchased_only_anlas(self):
        fake_data = {
            "active": True,
            "tier": 2,
            "trainingStepsLeft": {
                "fixedTrainingStepsLeft": 0,
                "purchasedTrainingSteps": 500,
            },
            "usage": {
                "percent": 0.0,
                "timeUntilNextPercent": 0,
            },
        }
        mock_session = MagicMock()
        mock_session.get.return_value = FakeResponse(200, fake_data)

        info = inquire_novelai_usage("pst-valid-token-secret-1234", session=mock_session)

        self.assertTrue(info.configured)
        self.assertEqual(info.tier, 2)
        self.assertEqual(info.tier_name, "Scroll")
        self.assertEqual(info.anlas, 500)
        self.assertEqual(info.usage_percent, 0.0)
        self.assertFalse(info.unlimited_v5_eligible)

    def test_inquire_http_401(self):
        mock_session = MagicMock()
        mock_session.get.return_value = FakeResponse(401, text="Unauthorized")

        info = inquire_novelai_usage("pst-bad-token", session=mock_session)

        self.assertTrue(info.configured)
        self.assertFalse(info.active)
        self.assertIn("Token 无效或已过期", info.error)

    def test_inquire_network_error(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = ConnectionError("Failed to resolve image.novelai.net")

        info = inquire_novelai_usage("pst-token-abc", session=mock_session)

        self.assertTrue(info.configured)
        self.assertFalse(info.active)
        self.assertIn("连接失败", info.error)

    def test_format_usage_summary(self):
        info = NovelAIUsageInfo(
            configured=True,
            token_masked="pst-...cdef",
            active=True,
            tier=3,
            tier_name="Opus",
            anlas=10000,
            fixed_anlas=10000,
            purchased_anlas=0,
            usage_percent=100.0,
            time_until_next_percent=0.0,
            unlimited_v5_eligible=True,
        )
        summary = format_usage_summary(info)
        self.assertIn("Opus", summary)
        self.assertIn("10,000", summary)
        self.assertIn("100.0%", summary)


if __name__ == "__main__":
    unittest.main()
