import os
import unittest
from unittest.mock import patch

from config import get_settings


class ConfigTest(unittest.TestCase):
    def test_development_mode_enables_debug_by_default(self):
        with patch.dict(os.environ, {"APP_ENV": "development"}, clear=False):
            settings = get_settings()
        self.assertTrue(settings["DEBUG"])
        self.assertEqual(settings["PROXY_COUNT"], 0)

    def test_production_mode_requires_a_strong_secret(self):
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "SECRET_KEY": "short"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                get_settings()

    def test_production_mode_rejects_the_known_development_secret(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "SECRET_KEY": "development-only-change-before-production",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                get_settings()

    def test_production_mode_uses_waitress_settings(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "APP_DEBUG": "false",
                "SECRET_KEY": "0123456789abcdef0123456789abcdef",
                "WAITRESS_THREADS": "24",
            },
            clear=False,
        ):
            settings = get_settings()
        self.assertFalse(settings["DEBUG"])
        self.assertEqual(settings["PROXY_COUNT"], 1)
        self.assertEqual(settings["WAITRESS_THREADS"], 24)


if __name__ == "__main__":
    unittest.main()
