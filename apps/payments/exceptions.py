"""
API errors for payment-gateway guards on the existing payments API.

Body format: {"detail": "...", "code": "..."} (DRF's default "detail" plus a
stable machine-readable code). Raised only in gateway-related cases, so the
manual payment flow keeps its existing responses.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class PaymentGuardError(APIException):
    error_code = "PAYMENT_GUARD_ERROR"

    def __init__(self, detail=None):
        detail = detail or self.default_detail
        self.message = str(detail)
        super().__init__({"detail": detail, "code": self.error_code})


class GatewayPaymentReadOnly(PaymentGuardError):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "GATEWAY_PAYMENT_READONLY"
    default_detail = "Payment gateway records cannot be changed."


class InvoiceLocked(PaymentGuardError):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "INVOICE_LOCKED"
    default_detail = "This invoice is in an active online payment."
