"""
Translate between provider-neutral dataclasses and DANA payloads.

This is the only place that knows DANA field names, responseCode values and
latestTransactionStatus codes.
"""

import datetime
from decimal import Decimal, InvalidOperation

from payment_aggregator.base import (
    BillingResult,
    BillingStatus,
    CancelResult,
    RefundResult,
    RefundStatus,
    SettlementStatus,
    TransferResult,
    TransferStatus,
)
from payment_aggregator.banks import BANKS
from payment_aggregator.exceptions import (
    BillingNotCancellable,
    BillingNotFound,
    DuplicateTransfer,
    InsufficientProviderBalance,
    InvalidAmount,
    InvalidCallback,
    InvalidDestinationAccount,
    InvalidPayerPhone,
    ProviderAccessDenied,
    ProviderRejected,
    ProviderUnavailable,
    RefundRejected,
    TransferNotFound,
)
from payment_aggregator.providers.dana import constants as c
from payment_aggregator.providers.dana.signing import WIB

# --- helpers --------------------------------------------------------------


def money(amount):
    """DANA Money: {"value": "10000.00", "currency": "IDR"}."""
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidAmount("Amount is not a number")
    if value != value.to_integral_value():
        raise InvalidAmount("Amount must be whole rupiah")
    return {"value": "{:.2f}".format(value), "currency": c.CURRENCY}


def whole_rupiah(amount):
    """Decimal amount -> int rupiah; InvalidAmount for fractions."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidAmount("Amount is not a number")
    if value != value.to_integral_value():
        raise InvalidAmount("Amount must be whole rupiah")
    return int(value)


def money_value(field):
    if not isinstance(field, dict):
        return None
    try:
        return Decimal(str(field.get("value")))
    except (InvalidOperation, ValueError):
        return None


def wib_datetime(value):
    """aware datetime -> "YYYY-MM-DDTHH:mm:ss+07:00"."""
    if value.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")
    return value.astimezone(WIB).strftime("%Y-%m-%dT%H:%M:%S+07:00")


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _code(body):
    return str(body.get("responseCode") or "")


def _message(body):
    return str(body.get("responseMessage") or "")


def _raise_for_common(body, what):
    """Errors shared by every DANA API; returns normally on anything else."""
    code, message = _code(body), _message(body)
    if code.startswith(c.RETRYABLE_PREFIXES) or code in c.RETRYABLE_CODES:
        # Outcome unknown: the caller must not treat it as failed.
        raise ProviderUnavailable("DANA {} pending ({})".format(what, code), provider_message=message, raw=body)
    if code.startswith("401"):
        raise ProviderAccessDenied("DANA denied the request ({})".format(code), provider_message=message, raw=body)


# --- pay-in ---------------------------------------------------------------


def order_payload(request, config):
    channel = c.CHANNELS.get(request.channel_code)
    if channel is None:
        raise ProviderRejected("Unknown DANA channel {}".format(request.channel_code))
    pay_option = {
        "payMethod": channel["pay_method"],
        "payOption": request.channel_code,
        "transAmount": money(request.amount),
    }
    if channel["pay_method"] in c.PHONE_REQUIRED_PAY_METHODS:
        phone = request.payer_phone or ""
        if not phone.startswith("62") or not phone.isdigit() or len(phone) > c.PHONE_MAX:
            raise InvalidPayerPhone("DANA requires an Indonesian phone number (62..., max 15 digits)")
        pay_option["additionalInfo"] = {"phoneNumber": phone}
    title = (request.note or request.reference_no)[: c.ORDER_TITLE_MAX]
    return {
        "partnerReferenceNo": request.reference_no,
        "merchantId": config.merchant_id,
        "amount": money(request.amount),
        "validUpTo": wib_datetime(request.expires_at),
        "urlParams": [
            {"url": config.notify_url, "type": "NOTIFICATION", "isDeeplink": "N"},
            {"url": config.return_url, "type": "PAY_RETURN", "isDeeplink": "N"},
        ],
        "payOptionDetails": [pay_option],
        "additionalInfo": {
            "mcc": config.mcc,
            "order": {"orderTitle": title, "scenario": "API"},
            "envInfo": {"sourcePlatform": "IPG", "terminalType": "SYSTEM", "orderTerminalType": "SYSTEM"},
        },
    }


def raise_for_order_response(body):
    if _code(body) == c.RESPONSE_CREATE_SUCCESS:
        return
    _raise_for_common(body, "order")
    # 4045418 (same partnerReferenceNo, different content) and every other
    # 4xx/5xx: the order was not created.
    raise ProviderRejected("DANA rejected the order ({})".format(_code(body)), provider_message=_message(body), raw=body)


def order_result(body, reference_no):
    info = body.get("additionalInfo") or {}
    return BillingResult(
        reference_no=str(body.get("partnerReferenceNo") or reference_no),
        provider_trx_id=str(body.get("referenceNo") or ""),
        status=BillingStatus.PENDING,
        payment_code=str(info.get("paymentCode") or ""),
        payment_link=str(body.get("webRedirectUrl") or ""),
        raw=body,
    )


def query_payload(provider_trx_id, config):
    return {
        "originalReferenceNo": provider_trx_id,
        "serviceCode": c.SERVICE_CODE_PAYMENT,
        "merchantId": config.merchant_id,
    }


def raise_for_query_response(body):
    code = _code(body)
    if code == c.RESPONSE_QUERY_SUCCESS:
        if str(body.get("latestTransactionStatus") or "") == c.STATUS_NOT_FOUND:
            raise BillingNotFound("DANA order not found", provider_message=_message(body), raw=body)
        return
    if code == c.RESPONSE_QUERY_NOT_FOUND:
        raise BillingNotFound("DANA order not found", provider_message=_message(body), raw=body)
    _raise_for_common(body, "query")
    # DANA: a failed query leaves the payment pending.
    raise ProviderUnavailable("DANA query failed ({})".format(code), provider_message=_message(body), raw=body)


def _billing_status(body):
    paid = str(body.get("latestTransactionStatus") or "") in c.STATUS_PAID
    # Cancelled ("05") stays PENDING: expiry is decided by the application.
    return BillingStatus.PAID if paid else BillingStatus.PENDING


def query_result(body):
    status = _billing_status(body)
    return BillingResult(
        reference_no=str(body.get("originalPartnerReferenceNo") or ""),
        provider_trx_id=str(body.get("originalReferenceNo") or ""),
        status=status,
        # Settlement comes from DANA's daily settlement file, not this API.
        settlement_status=SettlementStatus.NOT_SETTLED,
        amount=money_value(body.get("amount")),
        paid_at=parse_datetime(body.get("paidTime")) if status == BillingStatus.PAID else None,
        raw=body,
    )


# --- cancel / refund ------------------------------------------------------


def cancel_payload(reference_no, provider_trx_id, reason, config):
    payload = {"originalPartnerReferenceNo": reference_no, "merchantId": config.merchant_id}
    if provider_trx_id:
        payload["originalReferenceNo"] = provider_trx_id
    if reason:
        payload["reason"] = reason[:256]
    return payload


def raise_for_cancel_response(body):
    code = _code(body)
    if code == c.RESPONSE_CANCEL_SUCCESS:
        return
    _raise_for_common(body, "cancel")
    if code == c.RESPONSE_CANCEL_NOT_FOUND:
        raise BillingNotFound("DANA order not found", provider_message=_message(body), raw=body)
    if code in c.RESPONSE_CANCEL_NOT_ALLOWED:
        raise BillingNotCancellable(
            "DANA cannot cancel this order ({})".format(code), provider_message=_message(body), raw=body
        )
    raise ProviderRejected("DANA rejected the cancel ({})".format(code), provider_message=_message(body), raw=body)


def cancel_result(body, reference_no):
    return CancelResult(
        reference_no=str(body.get("originalPartnerReferenceNo") or reference_no),
        provider_trx_id=str(body.get("originalReferenceNo") or ""),
        cancelled_at=parse_datetime(body.get("cancelTime")),
        raw=body,
    )


def refund_payload(request, config):
    payload = {
        "merchantId": config.merchant_id,
        "originalPartnerReferenceNo": request.reference_no,
        "partnerRefundNo": request.refund_no,
        "refundAmount": money(request.amount),
        "sourcePlatform": "IPG",
        "orderTerminalType": "SYSTEM",
        "terminalType": "SYSTEM",
        "additionalInfo": {
            "actorContext": {"actorId": config.merchant_id, "actorType": c.REFUND_ACTOR_TYPE},
        },
    }
    if request.provider_trx_id:
        payload["originalReferenceNo"] = request.provider_trx_id
    if request.reason:
        payload["reason"] = request.reason[:256]
    return payload


def raise_for_refund_response(body):
    code = _code(body)
    if code == c.RESPONSE_REFUND_SUCCESS:
        return
    _raise_for_common(body, "refund")
    if code == c.RESPONSE_REFUND_INCONSISTENT:
        # Same refund number, different content: a previous attempt may have
        # gone through. Outcome unknown, never "failed".
        raise ProviderUnavailable(
            "DANA refund inconsistent with an earlier request ({})".format(code),
            provider_message=_message(body),
            raw=body,
        )
    raise RefundRejected("DANA rejected the refund ({})".format(code), provider_message=_message(body), raw=body)


def refund_result(body, request):
    return RefundResult(
        refund_no=str(body.get("partnerRefundNo") or request.refund_no),
        provider_refund_id=str(body.get("refundNo") or ""),
        status=RefundStatus.SUCCESS,
        amount=money_value(body.get("refundAmount")) or request.amount,
        refunded_at=parse_datetime(body.get("refundTime")),
        provider_message=_message(body),
        raw=body,
    )


# --- payout: Disbursement to Bank -----------------------------------------


def dana_bank(bank_code):
    """Classping bank code -> BI bank code DANA expects."""
    bank = BANKS.get(bank_code)
    if bank is None:
        raise InvalidDestinationAccount("Bank {} is not supported by DANA".format(bank_code))
    return bank[0]


def bank_inquiry_payload(request, config, bank_code, amount_sent):
    return {
        "partnerReferenceNo": request.reference_no,
        "customerNumber": config.payout_phone,
        "beneficiaryAccountNumber": request.account_number,
        "amount": money(amount_sent),
        "additionalInfo": {
            "fundType": c.FUND_TYPE_BANK,
            "chargeTarget": c.CHARGE_TARGET,
            "beneficiaryBankCode": bank_code,
            "beneficiaryAccountName": request.account_name[: c.ACCOUNT_NAME_MAX],
        },
    }


def raise_for_bank_inquiry(body):
    code = _code(body)
    if code == c.RESPONSE_INQUIRY_SUCCESS:
        return
    if code.startswith("401"):
        raise ProviderAccessDenied("DANA denied the request ({})".format(code), provider_message=_message(body), raw=body)
    if code in c.RESPONSE_INQUIRY_INVALID_ACCOUNT:
        raise InvalidDestinationAccount(
            "DANA rejected the bank account ({})".format(code), provider_message=_message(body), raw=body
        )
    if code == c.RESPONSE_INQUIRY_INSUFFICIENT:
        raise InsufficientProviderBalance(
            "DANA disbursement balance is insufficient ({})".format(code), provider_message=_message(body), raw=body
        )
    # Nothing has been sent yet: any other answer is a plain rejection.
    raise ProviderRejected("DANA account inquiry failed ({})".format(code), provider_message=_message(body), raw=body)


def transfer_payload(request, config, bank_code, amount_sent):
    return {
        "partnerReferenceNo": request.reference_no,
        "customerNumber": config.payout_phone,
        "beneficiaryAccountNumber": request.account_number,
        "beneficiaryBankCode": bank_code,
        "amount": money(amount_sent),
        "additionalInfo": {
            "fundType": c.FUND_TYPE_BANK,
            "chargeTarget": c.CHARGE_TARGET,
            "needNotify": True,
            "beneficiaryAccountName": request.account_name[: c.ACCOUNT_NAME_MAX],
        },
    }


def raise_for_transfer(body):
    """Returns for success / in progress; raises otherwise."""
    code = _code(body)
    if code in (c.RESPONSE_TRANSFER_SUCCESS, c.RESPONSE_TRANSFER_IN_PROGRESS):
        return
    if code == c.RESPONSE_TRANSFER_INCONSISTENT:
        # An earlier request with this reference exists: keep it, check it.
        raise DuplicateTransfer("DANA reports an earlier transfer with this reference", provider_message=_message(body), raw=body)
    _raise_for_common(body, "transfer")  # 429 / 5004301: outcome unknown
    if code == c.RESPONSE_TRANSFER_INSUFFICIENT:
        raise InsufficientProviderBalance(
            "DANA disbursement balance is insufficient", provider_message=_message(body), raw=body
        )
    if code in c.RESPONSE_TRANSFER_INVALID_ACCOUNT:
        raise InvalidDestinationAccount(
            "DANA rejected the bank account ({})".format(code), provider_message=_message(body), raw=body
        )
    raise ProviderRejected("DANA rejected the transfer ({})".format(code), provider_message=_message(body), raw=body)


def transfer_result(body, inquiry, request, amount_sent):
    success = _code(body) == c.RESPONSE_TRANSFER_SUCCESS
    fee = money_value((inquiry.get("additionalInfo") or {}).get("feeAmount"))
    return TransferResult(
        reference_no=request.reference_no,
        # Status checks are keyed by our partnerReferenceNo.
        provider_transfer_id=request.reference_no,
        status=TransferStatus.SUCCESS if success else TransferStatus.PROCESSING,
        provider_status_code=_code(body),
        provider_message=_message(body),
        amount_requested=Decimal(str(request.amount)),
        fee=fee,
        amount_received=Decimal(amount_sent),
        raw={"inquiry": inquiry, "transfer": body},
    )


def transfer_status_payload(provider_transfer_id):
    return {"originalPartnerReferenceNo": provider_transfer_id, "serviceCode": c.SERVICE_CODE_TRANSFER_STATUS}


def transfer_status_result(body, provider_transfer_id):
    code = _code(body)
    if code == c.RESPONSE_TRANSFER_STATUS_NOT_FOUND:
        raise TransferNotFound("DANA transfer not found", provider_message=_message(body), raw=body)
    if code != c.RESPONSE_TRANSFER_STATUS_SUCCESS:
        _raise_for_common(body, "transfer status")
        # DANA: a failed status inquiry leaves the transfer pending.
        raise ProviderUnavailable("DANA transfer status failed ({})".format(code), provider_message=_message(body), raw=body)
    return _transfer_status(body, provider_transfer_id)


def _transfer_status(body, provider_transfer_id):
    raw_status = str(body.get("latestTransactionStatus") or "")
    if raw_status == c.TRANSFER_STATUS_NOT_FOUND:
        raise TransferNotFound("DANA transfer not found", provider_message=_message(body), raw=body)
    if raw_status in c.TRANSFER_STATUS_SUCCESS:
        status = TransferStatus.SUCCESS
    elif raw_status in c.TRANSFER_STATUS_FAILED:
        status = TransferStatus.FAILED
    else:
        status = TransferStatus.PROCESSING
    return TransferResult(
        reference_no=str(body.get("originalPartnerReferenceNo") or provider_transfer_id),
        provider_transfer_id=str(body.get("originalPartnerReferenceNo") or provider_transfer_id),
        status=status,
        provider_status_code=raw_status,
        provider_message=str(body.get("transactionStatusDesc") or _message(body)),
        needs_review=raw_status not in (
            c.TRANSFER_STATUS_SUCCESS + c.TRANSFER_STATUS_PROCESSING + c.TRANSFER_STATUS_FAILED
        ),
        amount_received=money_value(body.get("amount")),
        raw=body,
    )


def notify_transfer_result(body):
    """Transfer to Bank notification (signature already verified). Only used
    to find the withdrawal: the application confirms it with the status
    inquiry (confirm_transfer_callbacks)."""
    reference = str(body.get("originalPartnerReferenceNo") or body.get("partnerReferenceNo") or "")
    if not reference:
        raise InvalidCallback("DANA transfer notification without a partner reference")
    raw_status = str(body.get("latestTransactionStatus") or "")
    if raw_status in c.TRANSFER_STATUS_SUCCESS:
        status = TransferStatus.SUCCESS
    elif raw_status in c.TRANSFER_STATUS_FAILED:
        status = TransferStatus.FAILED
    else:
        status = TransferStatus.PROCESSING
    return TransferResult(
        reference_no=reference,
        provider_transfer_id=reference,
        status=status,
        provider_status_code=raw_status,
        raw=body,
    )


def notify_result(body):
    """Finish Notify body -> BillingResult."""
    status = _billing_status(body)
    payment_info = (body.get("additionalInfo") or {}).get("paymentInfo") or {}
    paid_at = parse_datetime(payment_info.get("paidTime")) or parse_datetime(body.get("finishedTime"))
    return BillingResult(
        reference_no=str(body.get("originalPartnerReferenceNo") or ""),
        provider_trx_id=str(body.get("originalReferenceNo") or ""),
        status=status,
        settlement_status=SettlementStatus.NOT_SETTLED,
        amount=money_value(body.get("amount")),
        paid_at=paid_at if status == BillingStatus.PAID else None,
        raw=body,
    )
