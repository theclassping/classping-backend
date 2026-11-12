"""
Test helpers for Classping: the library's fakes, with a provider that uses
Classping's Rintisan rates.
"""

from payment_aggregator.testing import (  # noqa: F401
    CLIENT_ID,
    FakeResponse,
    FakeSession,
    key_pair,
    make_config,
)
from payment_aggregator.testing import make_provider as _make_provider

from apps.payment_aggregator.providers import rintisan


def make_provider(*responses, **config_overrides):
    """A RintisanProvider with Classping's rates, answering with ``responses``."""
    config_overrides.setdefault("payer_email", rintisan.PAYER_EMAIL)
    return _make_provider(
        *responses,
        channel_fees=rintisan.CHANNEL_FEES,
        disbursement_fee=rintisan.DISBURSEMENT_FEE,
        **config_overrides,
    )
