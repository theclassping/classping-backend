"""
Classping's payment aggregator settings: which provider, with Classping's
contract rates. The provider code itself is the ``payment_aggregator``
library (libs/payment_aggregator).

Checkout rules live in apps/payment_gateway/constants.py, withdrawal rules in
apps/wallets/constants.py.
"""

from decimal import Decimal

# --- Rintisan contract (Pricing & SLA deck) -------------------------------

# Virtual Account MDR, flat per transaction ("mulai dari Rp5.000", negotiable
# above 1000 trx/month). Paid by the parent on top of the invoice total.
RINTISAN_MDR_VA = Decimal("5000")

# Online Credit Card Rintisan MDR, percent. Paid by the parent via gross-up.
RINTISAN_MDR_CC = Decimal("2")

# E-commerce MDR, percent. Paid by the parent via gross-up.
RINTISAN_MDR_TOKOPEDIA_CC = Decimal("1.75")
RINTISAN_MDR_TOKOPEDIA_NON_CC = Decimal("0.5")
RINTISAN_MDR_BLIBLI_CC = Decimal("1.75")

# Rate per channel code (payment_aggregator.providers.rintisan.constants.CHANNELS).
# A channel left out is not offered. QRIS is intentionally not offered (BI
# forbids charging QRIS MDR to the payer). VAPERMATA is not in the pricing
# deck; it uses the VA rate until Rintisan confirms.
RINTISAN_CHANNEL_FEES = {
    "VABCA": RINTISAN_MDR_VA,
    "VABRI": RINTISAN_MDR_VA,
    "VAMANDIRI": RINTISAN_MDR_VA,
    "VABNI": RINTISAN_MDR_VA,
    "VAPERMATA": RINTISAN_MDR_VA,
    "CC": RINTISAN_MDR_CC,
    "TOKOPEDIA CC": RINTISAN_MDR_TOKOPEDIA_CC,
    "TOKOPEDIA NON CC": RINTISAN_MDR_TOKOPEDIA_NON_CC,
    "BLIBLI CC": RINTISAN_MDR_BLIBLI_CC,
}

# Rintisan fee per disbursement (incl. bank validator), borne by the school.
# Rintisan deducts it from the sent amount: withdraw 100.000 -> the bank
# account receives 97.500. There is no min/max disbursement amount.
RINTISAN_DISBURSEMENT_FEE = Decimal("2500")

# --- Rintisan account ------------------------------------------------------

# Env var holding Classping's RSA private key (PEM) that signs Rintisan requests.
RINTISAN_PRIVATE_KEY_ENV = "CLASSPING_PRIVATE_KEY"

# Sent as to_email on every billing instead of the guardian's email, so payers
# never receive emails from Rintisan (all emails come from Classping).
# Overridable with env RINTISAN_PAYER_EMAIL.
RINTISAN_PAYER_EMAIL = "no-reply@hamanto.com"
