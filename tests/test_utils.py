"""Unit tests for formatting helpers and configuration defaults."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scan  # noqa: E402


class FmtSecsTests(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(scan.fmt_secs(0), "00:00")

    def test_minutes(self):
        self.assertEqual(scan.fmt_secs(59), "00:59")
        self.assertEqual(scan.fmt_secs(60), "01:00")
        self.assertEqual(scan.fmt_secs(3599), "59:59")

    def test_hours(self):
        self.assertEqual(scan.fmt_secs(3600), "1:00:00")
        self.assertEqual(scan.fmt_secs(3661), "1:01:01")

    def test_negative_clamped(self):
        self.assertEqual(scan.fmt_secs(-5), "00:00")


class CleanTextTests(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(scan.clean_text("  a \n b\t c "), "a b c")

    def test_none_becomes_empty(self):
        self.assertEqual(scan.clean_text(None), "")

    def test_truncates_to_width(self):
        result = scan.clean_text("x" * 100, width=10)
        self.assertEqual(len(result), 10)
        self.assertTrue(result.endswith("…"))

    def test_short_text_untouched(self):
        self.assertEqual(scan.clean_text("hello", width=10), "hello")


class DedupeJoinTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(scan.dedupe_join([]), "(none)")

    def test_preserves_order_and_dedupes(self):
        self.assertEqual(scan.dedupe_join(["b", "a", "b", "c"]), "b, a, c")

    def test_limit_adds_overflow_marker(self):
        self.assertEqual(scan.dedupe_join(["a", "b", "c"], limit=2), "a, b (+1)")


class ConfigTests(unittest.TestCase):
    def test_default_config_keys(self):
        required = {"interval", "poll", "start_on_launch", "geometry",
                    "bot_token", "chat_id"}
        self.assertTrue(required.issubset(scan.DEFAULT_CONFIG))

    def test_palette_has_core_tokens(self):
        for key in ("bg", "panel", "fg", "accent", "green", "warn", "red"):
            self.assertIn(key, scan.T)
            self.assertTrue(scan.T[key].startswith("#"))


class TelegramTests(unittest.TestCase):
    def test_missing_credentials(self):
        ok, err = scan.send_telegram("", "", "x")
        self.assertFalse(ok)
        self.assertIn("no token/chat", err)


if __name__ == "__main__":
    unittest.main()
