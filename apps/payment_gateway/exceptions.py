"""Payment gateway API errors: {"detail": "...", "code": "..."}."""

from rest_framework import status

from apps.core.exceptions import CodedAPIException


class StudentRequired(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "STUDENT_REQUIRED"
    default_detail = "student_id is required."


class InvalidInvoiceIds(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "INVALID_INVOICE_IDS"


class MixedStudent(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "MIXED_STUDENT"
    default_detail = "Invoices must belong to one student."


class MixedBranch(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "MIXED_BRANCH"
    default_detail = "Invoices must belong to one branch."


class GatewayDisabled(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "GATEWAY_DISABLED"
    default_detail = "Online payment is not enabled for this branch."


class InvoiceNotPayable(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "INVOICE_NOT_PAYABLE"


class ChannelNotAvailable(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "CHANNEL_NOT_AVAILABLE"


class PayerPhoneInvalid(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "PAYER_PHONE_INVALID"
    default_detail = "Guardian phone number is missing or invalid."


class CheckoutForbidden(CodedAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "CHECKOUT_FORBIDDEN"
    default_detail = "Only a guardian of the student can pay online."


class IdempotencyKeyRequired(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "IDEMPOTENCY_KEY_REQUIRED"
    default_detail = "Idempotency-Key header is required."


class IdempotencyKeyReused(CodedAPIException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "IDEMPOTENCY_KEY_REUSED"
    default_detail = "This Idempotency-Key was used for a different checkout."


class ProviderRejected(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "PROVIDER_REJECTED"
    default_detail = "Payment provider rejected the billing."


class CancelForbidden(CodedAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "CANCEL_FORBIDDEN"
    default_detail = "You cannot cancel this online payment."


class RefundForbidden(CodedAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "REFUND_FORBIDDEN"
    default_detail = "You cannot refund this online payment."


class RefundNotAllowed(CodedAPIException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "REFUND_NOT_ALLOWED"
    default_detail = "Only a paid online payment flagged for refund, not refunded yet, can be refunded."


class RefundNotSupported(CodedAPIException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "REFUND_NOT_SUPPORTED"
    default_detail = "This payment provider has no online refund; refund the payer manually."


class RefundRejected(CodedAPIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "REFUND_REJECTED"
    default_detail = "The payment provider refused the refund; the branch balance was restored."


class GatewayPaymentNotPending(CodedAPIException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "GATEWAY_PAYMENT_NOT_PENDING"
    default_detail = "Only a pending online payment can be cancelled."
