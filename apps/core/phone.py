"""
Phone number normalization shared across the project (payments, WhatsApp, ...).

Result: E.164 digits without "+" (e.g. "6281234567890"). Local Indonesian
numbers starting with "0" become "62...". Provider-specific rules (e.g. a
payment provider accepting only Indonesian numbers) belong to that provider.
"""

import re

MIN_DIGITS = 8
MAX_DIGITS = 15  # E.164 maximum


class InvalidPhoneNumber(ValueError):
    pass


def normalize_phone(phone_number):
    digits = re.sub(r"\D", "", str(phone_number or ""))
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    if not MIN_DIGITS <= len(digits) <= MAX_DIGITS:
        raise InvalidPhoneNumber("Invalid phone number: {!r}".format(phone_number))
    return digits
