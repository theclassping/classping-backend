"""
API errors for payment-gateway guards on the existing payments API.

Raised only in gateway-related cases, so the manual payment flow keeps its
existing responses.
"""

from rest_framework import status

from apps.core.exceptions import CodedAPIException


class GatewayPaymentReadOnly(CodedAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "GATEWAY_PAYMENT_READONLY"
    default_detail = "Payment gateway records cannot be changed."


class InvoiceLocked(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "INVOICE_LOCKED"
    default_detail = "This invoice is in an active online payment."
