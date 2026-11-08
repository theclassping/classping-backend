"""Wallet / withdrawal API errors: {"detail": "...", "code": "..."}."""

from rest_framework import status

from apps.core.exceptions import CodedAPIException


class WithdrawalForbidden(CodedAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "WITHDRAWAL_ROLE_FORBIDDEN"
    default_detail = "Only the branch principal or officer can manage withdrawals."


class BranchEmailMissing(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "BRANCH_EMAIL_MISSING"
    default_detail = "The branch has no email address to receive the OTP."


class PayoutAccountNotFound(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "PAYOUT_ACCOUNT_NOT_FOUND"
    default_detail = "Payout account not found."


class PayoutAccountRequired(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "PAYOUT_ACCOUNT_REQUIRED"
    default_detail = "Choose a saved payout account or enter bank_code, account_number and account_holder_name."


class PayoutBankNotSupported(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "PAYOUT_BANK_NOT_SUPPORTED"
    default_detail = "This bank is not supported."


class InvalidAmount(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "INVALID_AMOUNT"


class AmountBelowMinimum(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "AMOUNT_BELOW_MINIMUM"


class InsufficientBalance(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "INSUFFICIENT_BALANCE"
    default_detail = "The amount exceeds the available balance."


class FeeNotAcknowledged(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "FEE_NOT_ACKNOWLEDGED"
    default_detail = "The withdrawal fee must be acknowledged."


class OtpInvalid(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "OTP_INVALID"
    default_detail = "The OTP is incorrect."


class OtpExpired(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "OTP_EXPIRED"
    default_detail = "The OTP has expired or is unknown. Request a new one."


class OtpMaxAttempts(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "OTP_MAX_ATTEMPTS"
    default_detail = "Too many incorrect OTP attempts. Request a new one."


class OtpNotSent(CodedAPIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "OTP_NOT_SENT"
    default_detail = "The OTP email could not be sent. Try again."


class PayoutAccountInvalid(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "PAYOUT_ACCOUNT_INVALID"
    default_detail = "The bank rejected the destination account."


class WithdrawalRejected(CodedAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "WITHDRAWAL_REJECTED"
    default_detail = "The provider rejected the withdrawal; the balance was returned."


class ProviderBalanceInsufficient(CodedAPIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "PROVIDER_BALANCE_INSUFFICIENT"
    default_detail = "Withdrawals are temporarily unavailable; the balance was returned."


class WithdrawalNotStuck(CodedAPIException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "WITHDRAWAL_NOT_STUCK"
    default_detail = "Only a processing withdrawal without a provider id can be resent or resolved."
