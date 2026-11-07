"""
API error with a stable machine-readable code.

Body: {"detail": "...", "code": "SOME_CODE", **extra}. Keeps DRF's "detail"
key, so clients that only read "detail" keep working.
"""

from rest_framework.exceptions import APIException


class CodedAPIException(APIException):
    error_code = "ERROR"

    def __init__(self, detail=None, **extra):
        detail = detail or self.default_detail
        self.message = str(detail)
        super().__init__({"detail": detail, "code": self.error_code, **extra})
