"""
DOKU (Checkout + Kirim DOKU): Classping's rates and account settings.

Env: DOKU_ENV, DOKU_CLIENT_ID, DOKU_SECRET_KEY, DOKU_RETURN_URL, and for
payouts CLASSPING_DOKU_PRIVATE_KEY, DOKU_SENDER_* , DOKU_PAYOUT_AGENT_KEY,
DOKU_PAYOUT_ACCOUNT_NO (see payment_aggregator.providers.doku.config).

Checkout with one payment method per order: the parent pays the channel fee
on top of the bill, so the channel must be known before the order is created.
"""

from decimal import Decimal

from django.conf import settings
from payment_aggregator.providers.doku import DokuConfig, DokuProvider

from apps.payment_aggregator.constants import DISBURSEMENT_FEE as GENERAL_DISBURSEMENT_FEE
from apps.payment_aggregator.constants import with_vat

NAME = "doku"

# --- Contract rates (doku.com/pricing, 2026-11; listed before 11% VAT) ------
# DOKU deducts its fee from the paid amount (split settlement works on the
# net settlement amount), so percent channels are grossed up and paid by the
# parent, as with DANA.

# Virtual accounts: Rp4.000 (BCA Rp4.500) + VAT.
MDR_VA = with_vat(Decimal("4000"))  # 4440
MDR_VA_BCA = with_vat(Decimal("4500"))  # 4995

# Cards (Visa, Mastercard, JCB): 2.8% + Rp2.000, both + VAT.
MDR_CARD = with_vat(Decimal("2.8"))  # 3.108 %
MDR_CARD_FLAT = with_vat(Decimal("2000"))  # 2220

# E-wallets (percent + VAT). DANA and DOKU Wallet have one public rate.
# OVO, ShopeePay and LinkAja are published as ranges; until the contract
# names our tier, the TOP of each range is used so the branch is never short
# (the parent may pay slightly more than DOKU deducts). Lower them to the
# contract rate once known.
MDR_EWALLET = with_vat(Decimal("1.5"))  # 1.665 %  DANA, DOKU Wallet
MDR_OVO = with_vat(Decimal("3.18"))  # 3.5298 % (range 2% - 3.18%)
MDR_SHOPEEPAY = with_vat(Decimal("4"))  # 4.44 %   (range 2% - 4%)
MDR_LINKAJA = with_vat(Decimal("3.5"))  # 3.885 %  (range 2% - 3.5%, or Rp2.500 flat)

# Rate per DOKU Checkout payment method. A channel left out is not offered.
# QRIS is intentionally not offered (BI forbids charging QRIS MDR to the payer).
CHANNEL_FEES = {
    "VIRTUAL_ACCOUNT_BCA": MDR_VA_BCA,
    "VIRTUAL_ACCOUNT_BNI": MDR_VA,
    "VIRTUAL_ACCOUNT_BRI": MDR_VA,
    "VIRTUAL_ACCOUNT_BANK_MANDIRI": MDR_VA,
    "VIRTUAL_ACCOUNT_BANK_PERMATA": MDR_VA,
    "VIRTUAL_ACCOUNT_BANK_CIMB": MDR_VA,
    "VIRTUAL_ACCOUNT_BANK_DANAMON": MDR_VA,
    "VIRTUAL_ACCOUNT_BANK_SYARIAH_MANDIRI": MDR_VA,
    "EMONEY_DANA": MDR_EWALLET,
    "EMONEY_DOKU": MDR_EWALLET,
    "EMONEY_OVO": MDR_OVO,
    "EMONEY_SHOPEE_PAY": MDR_SHOPEEPAY,
    "EMONEY_LINKAJA": MDR_LINKAJA,
    "CREDIT_CARD": MDR_CARD,
}
CHANNEL_FLAT_FEES = {
    "CREDIT_CARD": MDR_CARD_FLAT,
}

# Fee per Kirim DOKU transfer: Classping's general rate for every provider
# (see constants.DISBURSEMENT_FEE). The branch account receives amount - fee.
DISBURSEMENT_FEE = GENERAL_DISBURSEMENT_FEE


# --- Account ---------------------------------------------------------------

# Env var holding Classping's own RSA private key (PEM) for the Kirim DOKU
# access token; its public key is uploaded to the DOKU dashboard.
PRIVATE_KEY_ENV = "CLASSPING_DOKU_PRIVATE_KEY"

# Path of our payment webhook (sent with every order as
# override_notification_url); DOKU_NOTIFY_URL overrides the full URL.
NOTIFY_PATH = "/api/webhooks/payment/"


def build():
    """Env: DOKU_* (see payment_aggregator.providers.doku.config). The notify
    URL defaults to SITE_URL + NOTIFY_PATH."""
    config = DokuConfig.from_env(
        private_key_env=PRIVATE_KEY_ENV,
        default_notify_url=settings.SITE_URL.rstrip("/") + NOTIFY_PATH,
    )
    return DokuProvider(
        config,
        channel_fees=CHANNEL_FEES,
        channel_flat_fees=CHANNEL_FLAT_FEES,
        disbursement_fee=DISBURSEMENT_FEE,
    )
