"""
Classping's PaymentAggregator: the ``payment_aggregator`` library configured
with Classping's provider, rates and credentials.

    from apps.payment_aggregator import PaymentAggregator

    PaymentAggregator.get_channels(invoice_total)
    PaymentAggregator.calculate_transaction_fee("VABCA", invoice_total)
    PaymentAggregator.create_billing(BillingRequest(...))
    PaymentAggregator.calculate_withdrawal(amount)
    PaymentAggregator.transfer_balance(TransferRequest(...))

The provider is built on first use (credentials are read from the
environment then), once per process.
"""

import threading

from payment_aggregator import PaymentAggregator as _PaymentAggregator
from payment_aggregator.providers.rintisan import RintisanConfig, RintisanProvider

from apps.payment_aggregator import constants

_lock = threading.Lock()
_aggregator = None


def build_provider():
    """Classping's Rintisan account and contract rates."""
    config = RintisanConfig.from_env(
        private_key_env=constants.RINTISAN_PRIVATE_KEY_ENV,
        default_payer_email=constants.RINTISAN_PAYER_EMAIL,
    )
    return RintisanProvider(
        config,
        channel_fees=constants.RINTISAN_CHANNEL_FEES,
        disbursement_fee=constants.RINTISAN_DISBURSEMENT_FEE,
    )


def get_aggregator():
    global _aggregator
    if _aggregator is None:
        with _lock:
            if _aggregator is None:
                _aggregator = _PaymentAggregator(build_provider())
    return _aggregator


def get_provider():
    return get_aggregator().provider


def set_provider(provider):
    """Override the active provider (tests). Pass None to reset."""
    global _aggregator
    with _lock:
        _aggregator = None if provider is None else _PaymentAggregator(provider)


class _ClasspingAggregator:
    """Forwards every call to the process-wide aggregator, so callers (and
    mock.patch targets such as "...PaymentAggregator.create_billing") work
    without holding an instance."""

    def __getattr__(self, name):
        return getattr(get_aggregator(), name)


PaymentAggregator = _ClasspingAggregator()
