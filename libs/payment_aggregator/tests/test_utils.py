from types import SimpleNamespace
from unittest import TestCase, mock

from payment_aggregator.utils import env_pem, safe_response_preview


class EnvPemTests(TestCase):
    def test_literal_newline_escapes_become_newlines(self):
        with mock.patch.dict("os.environ", {"KEY": "  a\\nb  "}, clear=True):
            self.assertEqual(env_pem("KEY"), "a\nb")
            self.assertEqual(env_pem("MISSING"), "")


class SafeResponsePreviewTests(TestCase):
    def test_masks_secrets_and_truncates(self):
        response = SimpleNamespace(text='{"token":"abc123","signature":"xyz","ok":"yes"}' + "x" * 50)
        preview = safe_response_preview(response, limit=40)
        self.assertNotIn("abc123", preview)
        self.assertIn("[REDACTED]", preview)
        self.assertTrue(preview.endswith("…[truncated]"))
