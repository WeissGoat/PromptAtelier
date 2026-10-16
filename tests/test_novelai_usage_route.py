from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from tags_machine_core.config import AppConfig, NovelAIConfig
from tags_machine_core.services.novelai_usage import NovelAIUsageInfo
from tags_machine_core.web.app import create_app


class TestNovelAIUsageRoute(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = TestClient(self.app)

    @patch("tags_machine_core.web.routes.novelai.inquire_novelai_usage")
    def test_get_usage_success(self, mock_inquire):
        mock_inquire.return_value = NovelAIUsageInfo(
            configured=True,
            token_masked="pst-...abcd",
            active=True,
            tier=3,
            tier_name="Opus",
            anlas=10000,
            fixed_anlas=10000,
            purchased_anlas=0,
            usage_percent=95.0,
            time_until_next_percent=120.0,
            unlimited_v5_eligible=True,
        )

        response = self.client.get("/api/novelai/usage")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["configured"])
        self.assertTrue(data["active"])
        self.assertEqual(data["tier_name"], "Opus")
        self.assertEqual(data["anlas"], 10000)
        self.assertEqual(data["usage_percent"], 95.0)

    @patch("tags_machine_core.web.routes.novelai.inquire_novelai_usage")
    def test_refresh_usage(self, mock_inquire):
        mock_inquire.return_value = NovelAIUsageInfo(
            configured=True,
            token_masked="pst-...abcd",
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

        response = self.client.post("/api/novelai/usage/refresh")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["usage_percent"], 100.0)


if __name__ == "__main__":
    unittest.main()
