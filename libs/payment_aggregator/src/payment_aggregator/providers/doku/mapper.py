"""
Translate between provider-neutral dataclasses and DOKU payloads.

This is the only place that knows DOKU field names, response codes and
status values.
"""

import datetime
import math
import re
from decimal import Decimal, InvalidOperation

from payment_aggregator.base import (
    BillingResult,
    BillingStatus,
    ProviderBalance,
    SettlementStatus,
    TransferResult,
    TransferStatus,
)
from payment_aggregator.exceptions import (
    BillingNotFound,
    DuplicateTransfer,
    InsufficientProviderBalance,
    InvalidAmount,
    InvalidDestinationAccount,
    ProviderAccessDenied,
    ProviderRejected,
    ProviderUnavailable,
    TransferNotFound,
)
from payment_aggregator.providers.doku import constants as c

# --- helpers --------------------------------------------------------------


def whole_rupiah(amount):
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidAmount("Amount is not a number")
    if value != value.to_integral_value():
        raise InvalidAmount("Amount must be whole rupiah")
    return int(value)


def money(amount):
    """SNAP Money: {"value": "10000.00", "currency": "IDR"}."""
    return {"value": "{:.2f}".format(whole_rupiah(amount)), "currency": c.CURRENCY}


def decimal_or_none(value):
    if isinstance(value, dict):
        value = value.get("value")
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_utc(value):
    """DOKU ISO 8601 timestamps ("2021-01-27T03:24:23Z") -> aware datetime."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _code(body):
    return str(body.get("responseCode") or "")


def _message(body):
    return str(body.get("responseMessage") or "")


def _digits(value):
    return re.sub(r"\D", "", value or "")


def split_name(full_name):
    """("Budi", "Santoso") from "Budi Santoso"; a single word is used twice
    (DOKU requires both parts)."""
    parts = (full_name or "").split()
    if not parts:
        return "", ""
    first = parts[0][: c.ACCOUNT_NAME_MAX]
    last = " ".join(parts[1:])[: c.ACCOUNT_NAME_MAX] or first
    return first, last


# --- pay-in: Checkout -----------------------------------------------------


def payment_due_minutes(expires_at, now):
    if expires_at.tzinfo is None:
        raise ValueError("expires_at must be timezone-aware")
    minutes = math.ceil((expires_at - now).total_seconds() / 60)
    return max(c.PAYMENT_DUE_MINUTES_MIN, min(minutes, c.PAYMENT_DUE_MINUTES_MAX))


def checkout_payload(request, config, now):
    if request.channel_code not in c.CHANNELS:
        raise ProviderRejected("Unknown DOKU channel {}".format(request.channel_code))
    if len(request.reference_no) > c.INVOICE_NUMBER_MAX:
        raise ProviderRejected("DOKU invoice_number is limited to {} characters".format(c.INVOICE_NUMBER_MAX))
    order = {
        "amount": whole_rupiah(request.amount),
        "invoice_number": request.reference_no,
        "currency": c.CURRENCY,
        # True: the result page sends the payer back to callback_url.
        "auto_redirect": bool(config.return_url),
    }
    if config.return_url:
        order["callback_url"] = config.return_url
        order["callback_url_result"] = config.return_url
    customer = {}
    # Checkout allows letters only in customer.name.
    name = re.sub(r"[^A-Za-z ]+", " ", request.payer_name or "")
    name = " ".join(name.split())[: c.CUSTOMER_NAME_MAX]
    if name:
        customer["name"] = name
    phone = _digits(request.payer_phone)[: c.CUSTOMER_PHONE_MAX]
    if phone:
        customer["phone"] = phone
    if request.payer_email:
        customer["email"] = request.payer_email
    payload = {
        "order": order,
        "payment": {
            "payment_due_date": payment_due_minutes(request.expires_at, now),
            "payment_method_types": [request.channel_code],
        },
        "additional_info": {"override_notification_url": config.notify_url},
    }
    if customer:
        payload["customer"] = customer
    return payload


def _error_messages(body):
    if not isinstance(body, dict):
        return ""
    messages = body.get("error_messages") or body.get("message") or []
    if isinstance(messages, str):
        return messages
    return "; ".join(str(m) for m in messages)


def checkout_result(status, body, reference_no):
    payment = ((body or {}).get("response") or {}).get("payment") or {}
    if status != 200 or not payment.get("url"):
        raise ProviderRejected(
            "DOKU rejected the order (HTTP {})".format(status), provider_message=_error_messages(body), raw=body
        )
    return BillingResult(
        reference_no=reference_no,
        # The Check Status API is keyed by invoice_number.
        provider_trx_id=reference_no,
        status=BillingStatus.PENDING,
        payment_link=str(payment["url"]),
        raw=body,
    )


def transaction_result(body):
    """Check Status response or HTTP notification -> BillingResult."""
    transaction = body.get("transaction") or {}
    order = body.get("order") or {}
    paid = str(transaction.get("status") or "").upper() == c.TRANSACTION_SUCCESS
    va = body.get("virtual_account_info") or {}
    reference_no = str(order.get("invoice_number") or "")
    return BillingResult(
        reference_no=reference_no,
        provider_trx_id=reference_no,
        status=BillingStatus.PAID if paid else BillingStatus.PENDING,
        # Settlement is reported in DOKU's settlement report, not here.
        settlement_status=SettlementStatus.NOT_SETTLED,
        channel_code=str((body.get("channel") or {}).get("id") or ""),
        amount=decimal_or_none(order.get("amount")),
        payment_code=str(va.get("virtual_account_number") or ""),
        paid_at=parse_utc(transaction.get("date")) if paid else None,
        raw=body,
    )


def status_result(status, body):
    if status == 404:
        raise BillingNotFound("DOKU order not found", provider_message=_error_messages(body), raw=body)
    if status != 200 or not isinstance(body, dict):
        raise ProviderUnavailable("DOKU status check failed (HTTP {})".format(status), raw=body)
    return transaction_result(body)


# --- payout: Kirim DOKU ---------------------------------------------------


def doku_bank(bank_code):
    bank = c.BANKS.get(bank_code)
    if bank is None:
        raise InvalidDestinationAccount("Bank {} is not supported by DOKU".format(bank_code))
    return bank


def transfer_id(reference_no, bank_id, account_number):
    """provider_transfer_id: Check Status needs our reference AND the
    beneficiary bank / account, so all three are kept together."""
    return "{}|{}|{}".format(reference_no, bank_id, account_number)


def parse_transfer_id(provider_transfer_id):
    parts = str(provider_transfer_id or "").split("|")
    if len(parts) != 3 or not all(parts):
        raise TransferNotFound("Not a DOKU transfer id: {}".format(provider_transfer_id))
    return parts


def _raise_access_or_unavailable(body, what):
    code = _code(body)
    if code.startswith("401"):
        raise ProviderAccessDenied("DOKU denied the {} ({})".format(what, code), provider_message=_message(body), raw=body)
    if code.startswith(("5", "202")):
        raise ProviderUnavailable("DOKU {} outcome unknown ({})".format(what, code), provider_message=_message(body), raw=body)


def inquiry_payload(request, config, bank_id, amount):
    additional = {
        "beneficiaryBankCode": bank_id,
        "beneficiaryAccountName": request.account_name[: c.ACCOUNT_NAME_MAX],
        "senderCountryCode": c.SENDER_COUNTRY_CODE,
    }
    if config.payout_channel_code:
        additional["channelCode"] = config.payout_channel_code
    return {
        "partnerReferenceNo": request.reference_no,
        "customerNumber": config.sender_phone,
        "beneficiaryAccountNumber": request.account_number,
        "beneficiaryBankCode": bank_id,
        "amount": money(amount),
        "additionalInfo": additional,
    }


def raise_for_inquiry(body):
    """Account Inquiry comes before any money moves: every failure means
    nothing was sent."""
    code = _code(body)
    if code == c.RESPONSE_INQUIRY_SUCCESS and body.get("sessionId"):
        return
    if code.startswith("401"):
        raise ProviderAccessDenied("DOKU denied the account inquiry ({})".format(code), provider_message=_message(body), raw=body)
    if code in c.INQUIRY_INVALID_ACCOUNT:
        raise InvalidDestinationAccount("DOKU: beneficiary account invalid ({})".format(code), provider_message=_message(body), raw=body)
    raise ProviderRejected("DOKU account inquiry failed ({}); nothing was sent".format(code), provider_message=_message(body), raw=body)


def transfer_payload(request, config, bank, amount, inquiry):
    bank_id, bank_name = bank
    account_name = str(inquiry.get("beneficiaryAccountName") or request.account_name)[: c.ACCOUNT_NAME_MAX]
    first, last = split_name(account_name)
    additional = {
        "beneficiaryFirstName": first,
        "beneficiaryLastName": last,
        "beneficiaryPhoneNumber": _digits(request.phone) or config.sender_phone,
        "beneficiaryBankName": bank_name,
        "beneficiaryAccountName": account_name,
        "senderCountryCode": c.SENDER_COUNTRY_CODE,
        "senderFirstName": config.sender_first_name,
        "senderLastName": config.sender_last_name or config.sender_first_name,
        "senderPersonalId": config.sender_id_number,
        "senderPersonalIdType": config.sender_id_type,
        "remark": request.reference_no[: c.REMARK_MAX],
    }
    if config.payout_channel_code:
        additional["channelCode"] = config.payout_channel_code
    return {
        "partnerReferenceNo": request.reference_no,
        "customerNumber": config.sender_phone,
        "beneficiaryAccountNumber": request.account_number,
        "beneficiaryBankCode": bank_id,
        "amount": money(amount),
        "sessionId": str(inquiry["sessionId"]),
        "additionalInfo": additional,
    }


def raise_for_transfer(body):
    code = _code(body)
    if code in (c.RESPONSE_TRANSFER_SUCCESS, c.RESPONSE_TRANSFER_PENDING):
        return
    _raise_access_or_unavailable(body, "transfer")
    message = _message(body)
    if code in c.TRANSFER_INSUFFICIENT_FUNDS:
        raise InsufficientProviderBalance("DOKU balance insufficient ({})".format(code), provider_message=message, raw=body)
    if code in c.TRANSFER_INVALID_ACCOUNT:
        raise InvalidDestinationAccount("DOKU: beneficiary account invalid ({})".format(code), provider_message=message, raw=body)
    if code in c.TRANSFER_DUPLICATE:
        raise DuplicateTransfer("DOKU: transfer already processed ({})".format(code), provider_message=message, raw=body)
    raise ProviderRejected("DOKU rejected the transfer ({})".format(code), provider_message=message, raw=body)


def transfer_result(body, inquiry, request, bank_id, amount_sent):
    code = _code(body)
    success = code == c.RESPONSE_TRANSFER_SUCCESS
    fee = decimal_or_none((inquiry.get("additionalInfo") or {}).get("feeAmount"))
    return TransferResult(
        reference_no=request.reference_no,
        provider_transfer_id=transfer_id(request.reference_no, bank_id, request.account_number),
        status=TransferStatus.SUCCESS if success else TransferStatus.PROCESSING,
        provider_status_code=code,
        provider_message=_message(body),
        amount_requested=Decimal(str(request.amount)),
        # A zero / missing fee from DOKU is not reported (sandbox sends none).
        fee=fee if fee else None,
        amount_received=Decimal(amount_sent),
        raw={"inquiry": inquiry, "transfer": body},
    )


def status_payload(provider_transfer_id):
    reference_no, bank_id, account_number = parse_transfer_id(provider_transfer_id)
    return {
        "originalPartnerReferenceNo": reference_no,
        "serviceCode": c.SERVICE_CODE_TRANSFER,
        "beneficiaryAccountNumber": account_number,
        "beneficiaryBankCode": bank_id,
    }


_STATUS = {
    c.TRANSFER_STATUS_SUCCESS: TransferStatus.SUCCESS,
    c.TRANSFER_STATUS_PENDING: TransferStatus.PROCESSING,
    # Refunded: the money came back to Classping's DOKU balance.
    c.TRANSFER_STATUS_REFUNDED: TransferStatus.FAILED,
    c.TRANSFER_STATUS_FAILED: TransferStatus.FAILED,
}


def transfer_status_result(body, provider_transfer_id):
    code = _code(body)
    if code == c.RESPONSE_STATUS_NOT_FOUND:
        raise TransferNotFound("DOKU transfer not found", provider_message=_message(body), raw=body)
    if code != c.RESPONSE_STATUS_SUCCESS:
        _raise_access_or_unavailable(body, "status check")
        raise ProviderUnavailable("DOKU status check failed ({})".format(code), provider_message=_message(body), raw=body)
    latest = str(body.get("latestTransactionStatus") or "")
    status = _STATUS.get(latest, TransferStatus.PROCESSING)
    return TransferResult(
        reference_no=str(body.get("originalPartnerReferenceNo") or parse_transfer_id(provider_transfer_id)[0]),
        provider_transfer_id=provider_transfer_id,
        status=status,
        provider_status_code=latest,
        provider_message=str(body.get("transactionStatusDesc") or _message(body)),
        needs_review=latest not in _STATUS,
        amount_received=decimal_or_none((body.get("additionalInfo") or {}).get("beneficiaryAmount")),
        raw=body,
    )


_NOTIFY_STATUS = {
    c.NOTIFY_STATUS_SUCCESS: TransferStatus.SUCCESS,
    c.NOTIFY_STATUS_FAILED: TransferStatus.FAILED,
    c.NOTIFY_STATUS_REFUNDED: TransferStatus.FAILED,
    c.NOTIFY_STATUS_UNPAID: TransferStatus.PROCESSING,
}


def notify_transfer_result(body):
    """Unpaid / Refund notification -> TransferResult. The Refund
    notification has no status field; its message says "Refunded"."""
    raw_status = str(body.get("transactionStatus") or "")
    if not raw_status and "refund" in str(body.get("message") or "").lower():
        raw_status = c.NOTIFY_STATUS_REFUNDED
    status = _NOTIFY_STATUS.get(raw_status, TransferStatus.PROCESSING)
    return TransferResult(
        # sendTrxId is our partnerReferenceNo (= reference_no); DOKU's own
        # transactionId is kept in raw and echoed in the reply.
        reference_no=str(body.get("sendTrxId") or ""),
        provider_transfer_id="",
        status=status,
        provider_status_code=raw_status,
        provider_message=str(body.get("message") or ""),
        needs_review=raw_status not in _NOTIFY_STATUS,
        raw=body,
    )


def balance_result(body):
    code = _code(body)
    if code != c.RESPONSE_BALANCE_SUCCESS:
        _raise_access_or_unavailable(body, "balance inquiry")
        raise ProviderUnavailable("DOKU balance inquiry failed ({})".format(code), provider_message=_message(body), raw=body)
    infos = body.get("accountInfos") or {}
    # "avaliableBalance" is DOKU's spelling.
    available = decimal_or_none(infos.get("avaliableBalance") or infos.get("availableBalance"))
    return ProviderBalance(
        available=available if available is not None else Decimal("0"),
        pending=decimal_or_none(infos.get("holdAmount")) or Decimal("0"),
        raw=body,
    )
