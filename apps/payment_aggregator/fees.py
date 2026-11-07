"""
All fee formulas for payment gateway and withdrawals.

Provider-neutral: the numbers come from the active provider's constants via
Channel / WithdrawalRules. Views, serializers and other apps must not
re-implement any of this; go through PaymentAggregator.
"""

from decimal import ROUND_CEILING, Decimal, InvalidOperation

from apps.payment_aggregator.base import (
    FeeBreakdown,
    FeeType,
    WithdrawalBreakdown,
)
from apps.payment_aggregator.exceptions import (
    AmountAboveMaximum,
    AmountBelowMinimum,
    ChannelNotAvailable,
    InvalidAmount,
)

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def _to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise InvalidAmount("Amount is not a number")


def ceil_rupiah(value):
    """Round up to whole rupiah (providers only accept integer IDR)."""
    return value.to_integral_value(rounding=ROUND_CEILING)


def gross_up(net_amount, rate_percent):
    """Amount to charge so that, after a ``rate_percent`` MDR is deducted,
    at least ``net_amount`` remains:  total = net * 100 / (100 - rate)."""
    rate = _to_decimal(rate_percent)
    if rate < 0 or rate >= HUNDRED:
        raise ChannelNotAvailable("Invalid percentage rate")
    return ceil_rupiah(net_amount * HUNDRED / (HUNDRED - rate))


def is_channel_usable(channel):
    return channel.is_active and channel.fee is not None


def calculate_transaction_fee(channel, invoice_total):
    """Fee the payer pays on top of ``invoice_total`` for ``channel``.

    Raises ChannelNotAvailable when the channel is inactive, has no agreed
    rate yet, or the resulting amount is outside the channel's limits.
    """
    if not is_channel_usable(channel):
        raise ChannelNotAvailable("Channel {} is not available".format(channel.code))

    invoice_total = _to_decimal(invoice_total)
    if invoice_total <= 0:
        raise InvalidAmount("Invoice total must be greater than zero")

    fee = _to_decimal(channel.fee)
    if channel.fee_type == FeeType.FLAT:
        if fee < 0:
            raise ChannelNotAvailable("Invalid flat fee")
        amount = ceil_rupiah(invoice_total + fee)
    elif channel.fee_type == FeeType.PERCENT:
        amount = gross_up(invoice_total, fee)
    else:
        raise ChannelNotAvailable("Unknown fee type {}".format(channel.fee_type))

    if channel.min_amount is not None and amount < channel.min_amount:
        raise ChannelNotAvailable("Amount below the channel minimum")
    if channel.max_amount is not None and amount > channel.max_amount:
        raise ChannelNotAvailable("Amount above the channel maximum")

    return FeeBreakdown(
        channel_code=channel.code,
        channel_name=channel.name,
        payment_method=channel.method,
        invoice_total=invoice_total.quantize(CENT),
        transaction_fee=(amount - invoice_total).quantize(CENT),
        amount=amount.quantize(CENT),
    )


def available_channels(channels, invoice_total):
    """FeeBreakdown for every channel usable for ``invoice_total``."""
    result = []
    for channel in channels:
        try:
            result.append(calculate_transaction_fee(channel, invoice_total))
        except ChannelNotAvailable:
            continue
    return result


def calculate_withdrawal(rules, amount):
    """Split a withdrawal into fee and the amount actually transferred."""
    amount = _to_decimal(amount)
    if amount <= 0:
        raise InvalidAmount("Amount must be greater than zero")
    if amount != amount.to_integral_value():
        raise InvalidAmount("Amount must be whole rupiah")
    if amount < rules.min_amount:
        raise AmountBelowMinimum("Amount below the minimum withdrawal")
    if amount > rules.max_amount:
        raise AmountAboveMaximum("Amount above the maximum withdrawal")

    fee = _to_decimal(rules.fee)
    return WithdrawalBreakdown(
        amount=amount.quantize(CENT),
        fee=fee.quantize(CENT),
        transfer_amount=(amount - fee).quantize(CENT),
    )
