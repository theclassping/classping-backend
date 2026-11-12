"""
Translate between provider-neutral dataclasses and DANA payloads.

This is the only place that knows DANA field names, responseCode values and
latestTransactionStatus codes.
"""

import datetime
from decimal import Decimal, InvalidOperation

from payment_aggregator.base import BillingResult, BillingStatus, SettlementStatus
from payment_aggregator.exceptions import (
    BillingNotFound,
    InvalidAmount,
    InvalidPayerPhone,
    ProviderAccessDenied,
    ProviderRejected,
    ProviderUnavailable,
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
