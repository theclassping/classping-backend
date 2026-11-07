import hashlib
import hmac
import json
import logging
import re
import secrets
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com"


class WhatsappError(Exception):
    pass


class WhatsappService:
    """Send and verify OTP codes through a WhatsApp Cloud API authentication template."""

    @staticmethod
    def normalize_phone(phone_number):
        # Cloud API wants E.164 digits without "+"; local "08xx" numbers are Indonesian.
        digits = re.sub(r"\D", "", str(phone_number or ""))
        if digits.startswith("0"):
            digits = "62" + digits[1:]
        if not 8 <= len(digits) <= 15:
            raise WhatsappError(f"Invalid phone number: {phone_number!r}")
        return digits

    @classmethod
    def send_otp(cls, phone_number):
        """Generate an OTP, store its hash in the cache and send it. Returns the code."""
        phone = cls.normalize_phone(phone_number)
        code = "".join(secrets.choice("0123456789") for _ in range(settings.WHATSAPP_OTP_LENGTH))

        cls._send_template(
            to=phone,
            template_name=settings.WHATSAPP_OTP_TEMPLATE_NAME,
            language=settings.WHATSAPP_OTP_TEMPLATE_LANGUAGE,
            components=[
                {"type": "body", "parameters": [{"type": "text", "text": code}]},
                # The copy-code / one-tap button carries the code as its URL parameter.
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": code}],
                },
            ],
        )

        # Only store the code after a successful send, so a failed send leaves no valid OTP.
        cache.set(
            cls._cache_key(phone),
            {"hash": cls._hash(phone, code), "attempts": 0},
            timeout=settings.WHATSAPP_OTP_TTL_SECONDS,
        )
        logger.info("WhatsApp OTP sent to %s", cls._mask(phone))
        return code

    @classmethod
    def verify_otp(cls, phone_number, code):
        """Return True and consume the OTP if it matches; False otherwise."""
        phone = cls.normalize_phone(phone_number)
        key = cls._cache_key(phone)
        entry = cache.get(key)
        if not entry:
            return False

        if hmac.compare_digest(entry["hash"], cls._hash(phone, str(code or "").strip())):
            cache.delete(key)
            return True

        entry["attempts"] += 1
        if entry["attempts"] >= settings.WHATSAPP_OTP_MAX_ATTEMPTS:
            cache.delete(key)
        else:
            cache.set(key, entry, timeout=settings.WHATSAPP_OTP_TTL_SECONDS)
        return False

    @staticmethod
    def _send_template(*, to, template_name, language, components):
        if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
            raise WhatsappError("WhatsApp Cloud API is not configured.")

        url = (
            f"{GRAPH_API_URL}/{settings.WHATSAPP_API_VERSION}/"
            f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        )
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": components,
            },
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=settings.WHATSAPP_TIMEOUT_SECONDS) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise WhatsappError(f"WhatsApp API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise WhatsappError(f"WhatsApp API unreachable: {exc.reason}") from exc

    @staticmethod
    def _cache_key(phone):
        return f"whatsapp_otp:{phone}"

    @staticmethod
    def _hash(phone, code):
        return hmac.new(
            settings.SECRET_KEY.encode(), f"{phone}:{code}".encode(), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _mask(phone):
        return f"{phone[:4]}****{phone[-3:]}"
