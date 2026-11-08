"""
Translate between provider-neutral dataclasses and Rintisan payloads.

This is the only place that knows Rintisan field names, response_code values
and status codes.
"""

import datetime
import re
from decimal import Decimal, InvalidOperation

from apps.payment_aggregator.base import (
    BillingResult,
    BillingStatus,
    ProviderBalance,
    SettlementStatus,
    TransferResult,
    TransferStatus,
)
from apps.payment_aggregator.exceptions import (
    BillingNotFound,
    DuplicateBilling,
    DuplicateTransfer,
    InsufficientProviderBalance,
    InvalidAmount,
    InvalidDestinationAccount,
    InvalidPayerPhone,
    ProviderRejected,
    ProviderUnavailable,
    TransferNotFound,
)
from apps.payment_aggregator.providers.rintisan import constants as c

PROVIDER_TZ = datetime.timezone(
    datetime.timedelta(hours=c.PROVIDER_UTC_OFFSET_HOURS), name="WIB"
)

# --- helpers --------------------------------------------------------------


def to_idr_int(amount):
    """Rintisan amounts are whole IDR."""
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidAmount("Amount is not a number")
    if value != value.to_integral_value():
        raise InvalidAmount("Amount must be whole rupiah")
    return int(value)


def to_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_datetime(value):
    if not value:
        return None
    try:
        naive = datetime.datetime.strptime(value, c.PROVIDER_DATETIME_FORMAT)
    except (TypeError, ValueError):
        return None
    return naive.replace(tzinfo=PROVIDER_TZ)


def _response_code(body):
    code = body.get("response_code")
    return None if code is None else str(code)


def _message(body):
    return str(body.get("message") or "")


def _status_code(body):
    status = body.get("status")
    if isinstance(status, dict) and status.get("code") is not None:
        return str(status.get("code"))
    return ""


def _status_message(body):
    status = body.get("status")
    return str(status.get("message") or "") if isinstance(status, dict) else ""


# --- pay-in ---------------------------------------------------------------


def billing_payload(request, payer_email):
    """``payer_email`` replaces request.payer_email so Rintisan never emails payers."""
    if request.expires_at.tzinfo is None:
        raise ValueError("BillingRequest.expires_at must be timezone-aware")
    if not re.match(c.PAYER_PHONE_PATTERN, request.payer_phone or ""):
        raise InvalidPayerPhone("Rintisan requires an Indonesian phone number (62...)")
    return {
        "partner_trx_id": request.reference_no,
        "partner_identifier_id": request.identifier or request.reference_no,
        "invoice_date": request.invoice_date.isoformat(),
        # Rintisan's due date is a date: the WIB date of expires_at.
        "deadline_date": request.expires_at.astimezone(PROVIDER_TZ).date().isoformat(),
        "to_name": request.payer_name,
        "to_address": request.payer_address or "",
        "to_phone": request.payer_phone,
        "to_email": payer_email,
        "note": request.note or "",
        "payment_method": request.channel_code,
        "amount": to_idr_int(request.amount),
    }


def raise_for_billing_response(body):
    code = _response_code(body)
    message = _message(body)
    if code == c.RESPONSE_CODE_SUCCESS:
        return
    if code == c.RESPONSE_CODE_DUPLICATE:
        raise DuplicateBilling(
            "Billing reference already used",
            provider_trx_id=str(body.get("trx_id") or ""),
            provider_message=message,
            raw=body,
        )
    if code is None:
        raise ProviderUnavailable("Rintisan response without response_code", raw=body)
    if c.MESSAGE_TRANSACTION_NOT_FOUND in message.lower():
        raise BillingNotFound("Billing not found", provider_message=message, raw=body)
    raise ProviderRejected("Rintisan rejected the billing", provider_message=message, raw=body)


def billing_result(body, reference_no=""):
    """Build a BillingResult from a /create, /querypayment or callback body."""
    payment_status = str(body.get("payment_status") or "").upper()
    callback_code = _status_code(body)
    # Rintisan only reports PAID / UNPAID; expiry is decided by Classping.
    if payment_status == c.PAYMENT_STATUS_PAID or callback_code == c.CALLBACK_STATUS_SUCCESS:
        status = BillingStatus.PAID
    else:
        status = BillingStatus.PENDING

    disburse_status = str(body.get("disburse_status") or "").upper()
    settlement = (
        SettlementStatus.SETTLED
        if disburse_status == c.DISBURSE_STATUS_DISBURSED
        else SettlementStatus.NOT_SETTLED
    )

    return BillingResult(
        reference_no=str(body.get("partner_trx_id") or reference_no),
        provider_trx_id=str(body.get("trx_id") or ""),
        status=status,
        settlement_status=settlement,
        channel_code=str(body.get("payment_method") or ""),
        amount=to_decimal(body.get("total_amount")),
        payment_code=str(body.get("payment_code") or ""),
        payment_link=str(body.get("payment_link") or ""),
        billing_url=str(body.get("rintisan_billing_link") or ""),
        paid_at=parse_datetime(body.get("paid_at")),
        raw=body,
    )


# --- payout ---------------------------------------------------------------


def transfer_payload(request):
    payload = {
        "reference_id": request.reference_no,
        "amount": to_idr_int(request.amount),
        "name": request.account_name,
        "bank_code": request.bank_code,
        "account_number": request.account_number,
    }
    if request.email:
        payload["email"] = request.email
    if request.phone:
        payload["phone"] = request.phone
    return payload


def raise_for_transfer_response(body):
    code = _response_code(body)
    message = _message(body)
    lowered = message.lower()
    if code == c.RESPONSE_CODE_SUCCESS:
        return
    if code is None:
        raise ProviderUnavailable("Rintisan response without response_code", raw=body)
    if c.MESSAGE_INSUFFICIENT_BALANCE in lowered:
        raise InsufficientProviderBalance(
            "Provider balance insufficient", provider_message=message, raw=body
        )
    if c.MESSAGE_DUPLICATE_REFERENCE in lowered:
        raise DuplicateTransfer(
            "Transfer reference already used", provider_message=message, raw=body
        )
    if c.MESSAGE_INVALID_ACCOUNT in lowered or c.MESSAGE_INVALID_BANK in lowered:
        raise InvalidDestinationAccount(
            "Destination account rejected", provider_message=message, raw=body
        )
    raise ProviderRejected("Rintisan rejected the transfer", provider_message=message, raw=body)


def raise_for_transfer_status_response(body):
    """/statusdisbursement success has no response_code; errors do."""
    code = _response_code(body)
    if code is None or code == c.RESPONSE_CODE_SUCCESS:
        if not _status_code(body):
            raise ProviderUnavailable("Rintisan status without status.code", raw=body)
        return
    message = _message(body)
    if c.MESSAGE_DISBURSEMENT_NOT_FOUND in message.lower():
        raise TransferNotFound("Transfer not found", provider_message=message, raw=body)
    raise ProviderRejected("Rintisan rejected the status query", provider_message=message, raw=body)


def transfer_status(status_code):
    """Map Rintisan status.code -> (TransferStatus, needs_review)."""
    if status_code == c.DISBURSEMENT_STATUS_SUCCESS:
        return TransferStatus.SUCCESS, False
    if status_code == c.DISBURSEMENT_STATUS_FAILED:
        return TransferStatus.FAILED, False
    if status_code == c.DISBURSEMENT_STATUS_SUSPECT_ACCOUNT:
        return TransferStatus.PROCESSING, True
    # 201/202/203 and anything unknown: not final, keep processing.
    return TransferStatus.PROCESSING, status_code not in c.DISBURSEMENT_STATUS_PROCESSING


def transfer_result(body, reference_no=""):
    """Build a TransferResult from /makedisbursement, /statusdisbursement or callback."""
    status_code = _status_code(body)
    if status_code:
        status, needs_review = transfer_status(status_code)
    else:
        # /makedisbursement success: accepted, not final yet.
        status, needs_review = TransferStatus.PROCESSING, False

    return TransferResult(
        reference_no=str(body.get("partner_reference_id") or reference_no),
        provider_transfer_id=str(body.get("disbursement_id") or ""),
        status=status,
        provider_status_code=status_code,
        provider_message=_status_message(body),
        needs_review=needs_review,
        amount_requested=to_decimal(body.get("amount_request")),
        fee=to_decimal(body.get("disburse_fee")),
        amount_received=to_decimal(body.get("disburse_amount")),
        raw=body,
    )


# --- balance --------------------------------------------------------------


def raise_for_balance_response(body):
    code = _response_code(body)
    if code == c.RESPONSE_CODE_SUCCESS:
        return
    if code is None:
        raise ProviderUnavailable("Rintisan response without response_code", raw=body)
    raise ProviderRejected(
        "Rintisan rejected the balance query", provider_message=_message(body), raw=body
    )


def provider_balance(body):
    return ProviderBalance(
        available=to_decimal(body.get("balance")) or Decimal("0"),
        pending=to_decimal(body.get("balance_pending")) or Decimal("0"),
        raw=body,
    )
