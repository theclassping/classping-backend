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

from apps.payment_aggregator import constants


def make_provider(*responses, **config_overrides):
    """A RintisanProvider with Classping's rates, answering with ``responses``."""
    config_overrides.setdefault("payer_email", constants.RINTISAN_PAYER_EMAIL)
    return _make_provider(
        *responses,
        channel_fees=constants.RINTISAN_CHANNEL_FEES,
        disbursement_fee=constants.RINTISAN_DISBURSEMENT_FEE,
        **config_overrides,
    )
