import logging
import unittest
from unittest.mock import patch

from tags_machine_core.logging_config import (
    LOG_LEVEL_ENV,
    TRACE_LEVEL,
    configure_logging,
    normalize_log_level,
)


class LoggingConfigTest(unittest.TestCase):
    def test_default_log_level_is_error(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(normalize_log_level(None), logging.ERROR)

    def test_supported_log_levels(self):
        self.assertEqual(normalize_log_level("trace"), TRACE_LEVEL)
        self.assertEqual(normalize_log_level("info"), logging.INFO)
        self.assertEqual(normalize_log_level("warning"), logging.WARNING)
        self.assertEqual(normalize_log_level("error"), logging.ERROR)

    def test_env_log_level_is_used_when_cli_level_missing(self):
        with patch.dict("os.environ", {LOG_LEVEL_ENV: "info"}):
            self.assertEqual(normalize_log_level(None), logging.INFO)

    def test_configure_logging_sets_package_logger_level(self):
        configure_logging("warning")

        self.assertEqual(logging.getLogger("tags_machine_core").level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()
