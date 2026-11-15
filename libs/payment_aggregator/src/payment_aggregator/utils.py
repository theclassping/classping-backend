"""Helpers shared by every provider (environment reading, request/response logging)."""

import os
import re

# Secrets and payer personal data masked before a payload is logged.
_SECRET_FIELDS = re.compile(
    r'(?i)("?(?:x-api-key|api[_-]?key|token|authorization|x-signature|signature|private[_-]?key'
    r'|phone[_-]?number)"?\s*[:=]\s*"?)[^"&,\s}]+'
)


def env_pem(name):
    """PEM text from the environment; literal \\n escapes become newlines."""
    return os.environ.get(name, "").strip().replace("\\n", "\n")


def safe_preview(text, limit=1000):
    """Return a bounded sample of ``text`` with common secrets masked."""
    text = text or ""
    preview = _SECRET_FIELDS.sub(r"\1[REDACTED]", text[:limit])
    if len(text) > limit:
        preview += "…[truncated]"
    return preview


def safe_response_preview(response, limit=1000):
    """Return a bounded provider response sample with common secrets masked."""
    return safe_preview(response.text, limit)
