"""
Test helpers for Classping: the library's fakes, with a provider that uses
Classping's DANA rates.
"""

from payment_aggregator.testing import (  # noqa: F401
    DANA_PARTNER_ID,
    FakeResponse,
    FakeSession,
    dana_notify_headers,
    key_pair,
    make_dana_config,
)
from payment_aggregator.testing import make_dana_provider

from apps.payment_aggregator.providers import dana


def make_provider(*responses, **config_overrides):
    """A DanaProvider with Classping's rates, answering with ``responses``."""
    return make_dana_provider(
        *responses,
        channel_fees=dana.CHANNEL_FEES,
        disbursement_fee=dana.DISBURSEMENT_FEE,
        **config_overrides,
    )
