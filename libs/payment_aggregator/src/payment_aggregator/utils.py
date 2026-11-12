"""Helpers shared by every provider (environment reading, response logging)."""

import os
import re

_SECRET_FIELDS = re.compile(
    r'(?i)("?(?:x-api-key|api[_-]?key|token|authorization|x-signature|signature|private[_-]?key)"?\s*[:=]\s*"?)[^"&,\s}]+'
)


def env_pem(name):
    """PEM text from the environment; literal \\n escapes become newlines."""
    return os.environ.get(name, "").strip().replace("\\n", "\n")


def safe_response_preview(response, limit=1000):
    """Return a bounded provider response sample with common secrets masked."""
    preview = _SECRET_FIELDS.sub(r"\1[REDACTED]", response.text[:limit])
    if len(response.text) > limit:
        preview += "…[truncated]"
    return preview
