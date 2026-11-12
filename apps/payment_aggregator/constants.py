"""
Classping's provider-neutral payment aggregator settings.

Each provider's contract rates and account settings live in their own module
under apps/payment_aggregator/providers/ (rintisan.py, dana.py, ...). The
active provider is chosen with env PAYMENT_PROVIDER (config/settings.py).

Checkout rules live in apps/payment_gateway/constants.py, withdrawal rules in
apps/wallets/constants.py. The provider code itself is the
``payment_aggregator`` library (libs/payment_aggregator).
"""

from decimal import Decimal

# Indonesian VAT (PPN) a provider may add on top of its own fee.
VAT_RATE = Decimal("0.11")

# Classping's no-reply address, given to providers instead of the guardian's
# email so payers never receive provider emails (all emails come from Classping).
PAYER_EMAIL = "no-reply@hamanto.com"


def with_vat(fee):
    """A provider fee plus VAT, for providers that list their rates before VAT
    (a flat amount in rupiah or a percent rate)."""
    return fee * (1 + VAT_RATE)
