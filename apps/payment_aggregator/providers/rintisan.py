"""
Rintisan: Classping's contract rates (Pricing & SLA deck) and account settings.

Env: RINTISAN_ENV, RINTISAN_CLIENT_ID, RINTISAN_API_KEY, CLASSPING_PRIVATE_KEY,
RINTISAN_PUBLIC_KEY, RINTISAN_CALLBACK_TOKEN, RINTISAN_PAYER_EMAIL,
RINTISAN_REQUIRE_TRANSFER_CALLBACK_SIGNATURE.
"""

from decimal import Decimal

from payment_aggregator.providers.rintisan import RintisanConfig, RintisanProvider

from apps.payment_aggregator import constants

NAME = RintisanProvider.name  # "rintisan"

# --- Contract rates --------------------------------------------------------

# Virtual Account MDR, flat per transaction ("mulai dari Rp5.000", negotiable
# above 1000 trx/month). Paid by the parent on top of the invoice total.
MDR_VA = Decimal("5000")

# Online Credit Card Rintisan MDR, percent. Paid by the parent via gross-up.
MDR_CC = Decimal("2")

# E-commerce MDR, percent. Paid by the parent via gross-up.
MDR_TOKOPEDIA_CC = Decimal("1.75")
MDR_TOKOPEDIA_NON_CC = Decimal("0.5")
MDR_BLIBLI_CC = Decimal("1.75")

# Rate per channel code (payment_aggregator.providers.rintisan.constants.CHANNELS).
# A channel left out is not offered. QRIS is intentionally not offered (BI
# forbids charging QRIS MDR to the payer). VAPERMATA is not in the pricing
# deck; it uses the VA rate until Rintisan confirms.
CHANNEL_FEES = {
    "VABCA": MDR_VA,
    "VABRI": MDR_VA,
    "VAMANDIRI": MDR_VA,
    "VABNI": MDR_VA,
    "VAPERMATA": MDR_VA,
    "CC": MDR_CC,
    "TOKOPEDIA CC": MDR_TOKOPEDIA_CC,
    "TOKOPEDIA NON CC": MDR_TOKOPEDIA_NON_CC,
    "BLIBLI CC": MDR_BLIBLI_CC,
}

# Fee per disbursement (incl. bank validator), borne by the school. Rintisan
# deducts it from the sent amount: withdraw 100.000 -> the bank account
# receives 97.500. There is no min/max disbursement amount.
DISBURSEMENT_FEE = Decimal("2500")

# --- Account ---------------------------------------------------------------

# Env var holding Classping's RSA private key (PEM) that signs Rintisan requests.
PRIVATE_KEY_ENV = "CLASSPING_PRIVATE_KEY"

# Sent as to_email on every billing. Overridable with env RINTISAN_PAYER_EMAIL.
PAYER_EMAIL = constants.PAYER_EMAIL


def build():
    config = RintisanConfig.from_env(private_key_env=PRIVATE_KEY_ENV, default_payer_email=PAYER_EMAIL)
    return RintisanProvider(config, channel_fees=CHANNEL_FEES, disbursement_fee=DISBURSEMENT_FEE)
