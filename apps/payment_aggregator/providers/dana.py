"""
DANA (Gapura Custom Checkout + Disbursement to Bank): Classping's rates and
account settings.

Env: DANA_ENV, DANA_MERCHANT_ID, DANA_CLIENT_ID, DANA_CLIENT_SECRET,
DANA_CHANNEL_ID, DANA_PRIVATE_KEY, DANA_PUBLIC_KEY, DANA_RETURN_URL, and
optionally DANA_NOTIFY_URL, DANA_MCC, DANA_BASE_URL.

Custom Checkout, not Hosted Checkout: the parent pays the channel fee on top
of the bill, so the channel must be known before the order is created.
"""

from decimal import Decimal

from django.conf import settings
from payment_aggregator.providers.dana import DanaConfig, DanaProvider

from apps.payment_aggregator.constants import with_vat

NAME = "dana"

# --- Contract rates (DANA fee calculator, 2026-11) -------------------------
# DANA adds 11% VAT on top of its fee, so each rate is the listed fee + VAT.
# DANA deducts the fee from the paid amount (settlement file: SETTLE_AMOUNT =
# TXN_AMOUNT - commission - tax), so percent channels are grossed up and paid
# by the parent, as with Rintisan.

# Virtual account: Rp2.500 + VAT = Rp2.775 flat. Excludes the bank's own fee
# (agreed between Classping and each bank); add it per bank once known.
MDR_VA = with_vat(Decimal("2500"))  # 2775

# Cards (Visa, Mastercard, AMEX, JCB): 2.9% + VAT = 3.219%.
MDR_CARD = with_vat(Decimal("2.9"))  # 3.219

# Rate per DANA payOption. A channel left out is not offered. QRIS is
# intentionally not offered (BI forbids charging QRIS MDR to the payer).
# E-wallets (1.5% or 2% + VAT) are left out until DANA says which tier is ours.
CHANNEL_FEES = {
    "VIRTUAL_ACCOUNT_BCA": MDR_VA,
    "VIRTUAL_ACCOUNT_BNI": MDR_VA,
    "VIRTUAL_ACCOUNT_BRI": MDR_VA,
    "VIRTUAL_ACCOUNT_MANDIRI": MDR_VA,
    "VIRTUAL_ACCOUNT_PERMATA": MDR_VA,
    "NETWORK_PAY_PG_CARD": MDR_CARD,
}

# Fee per Transfer to Bank. Not in the fee calculator yet: None keeps
# withdrawals through DANA disabled until DANA confirms the amount and whether
# it is deducted from the transfer or charged separately.
DISBURSEMENT_FEE = None


# --- Account ---------------------------------------------------------------

# Merchant category code sent with every order: 8211 = elementary and
# secondary schools. Overridable with env DANA_MCC (use the MCC DANA registered).
MCC = "8211"

# Path of our payment webhook; DANA_NOTIFY_URL overrides the full URL.
NOTIFY_PATH = "/api/webhooks/payment/"


def build():
    """Env: DANA_* (see payment_aggregator.providers.dana.config). The notify
    URL defaults to SITE_URL + NOTIFY_PATH; DANA_RETURN_URL is required."""
    config = DanaConfig.from_env(
        default_mcc=MCC,
        default_notify_url=settings.SITE_URL.rstrip("/") + NOTIFY_PATH,
    )
    return DanaProvider(config, channel_fees=CHANNEL_FEES, disbursement_fee=DISBURSEMENT_FEE)
