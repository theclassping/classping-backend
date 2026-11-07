import json
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.whatsapp.services import WhatsappError, WhatsappService


LOCAL_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "whatsapp-tests"}}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@override_settings(
    CACHES=LOCAL_CACHE,
    WHATSAPP_ACCESS_TOKEN="test-token",
    WHATSAPP_PHONE_NUMBER_ID="123456",
    WHATSAPP_OTP_MAX_ATTEMPTS=3,
)
class WhatsappServiceTests(SimpleTestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def send(self, phone="081234567890"):
        with patch("urllib.request.urlopen", return_value=FakeResponse({"messages": [{"id": "wamid.1"}]})) as urlopen:
            code = WhatsappService.send_otp(phone)
        return code, urlopen.call_args.args[0]

    def test_normalize_phone(self):
        self.assertEqual(WhatsappService.normalize_phone("0812-3456-7890"), "6281234567890")
        self.assertEqual(WhatsappService.normalize_phone("+62 812 3456 7890"), "6281234567890")
        with self.assertRaises(WhatsappError):
            WhatsappService.normalize_phone("123")

    def test_send_otp_posts_authentication_template(self):
        code, request = self.send()

        self.assertEqual(len(code), 6)
        self.assertEqual(request.full_url, "https://graph.facebook.com/v23.0/123456/messages")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        body = json.loads(request.data)
        self.assertEqual(body["to"], "6281234567890")
        self.assertEqual(body["template"]["components"][0]["parameters"][0]["text"], code)
        self.assertEqual(body["template"]["components"][1]["parameters"][0]["text"], code)

    def test_verify_otp_is_single_use(self):
        code, _ = self.send()

        self.assertTrue(WhatsappService.verify_otp("+6281234567890", code))
        self.assertFalse(WhatsappService.verify_otp("+6281234567890", code))

    def test_verify_otp_locks_after_max_attempts(self):
        code, _ = self.send()

        for _ in range(3):
            self.assertFalse(WhatsappService.verify_otp("081234567890", "000000" if code != "000000" else "111111"))
        self.assertFalse(WhatsappService.verify_otp("081234567890", code))

    @override_settings(WHATSAPP_ACCESS_TOKEN="")
    def test_send_otp_requires_configuration(self):
        with self.assertRaises(WhatsappError):
            WhatsappService.send_otp("081234567890")
