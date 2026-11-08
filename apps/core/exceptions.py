"""
API error with a stable machine-readable code.

Body: {"detail": "...", "code": "SOME_CODE", **extra}. Keeps DRF's "detail"
key, so clients that only read "detail" keep working. Extra values keep their
JSON type (e.g. remaining_attempts: 2, not "2").
"""

from rest_framework.exceptions import APIException


class CodedAPIException(APIException):
    error_code = "ERROR"

    def __init__(self, detail=None, **extra):
        detail = detail or self.default_detail
        self.message = str(detail)
        super().__init__({"detail": detail, "code": self.error_code})
        self.detail.update(extra)


class ProviderUnavailable(CodedAPIException):
    """The payment provider could not be reached or refused the request."""

    status_code = 503
    error_code = "PROVIDER_UNAVAILABLE"
    default_detail = "Payment provider is unavailable, please try again."
