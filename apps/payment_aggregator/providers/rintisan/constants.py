"""
Rintisan fees, channels and limits.

Source: Rintisan "Pricing & SLA" deck and OpenAPI "Rintisan Payin Partner API"
v1.0.0 (https://docs.rintisan.co.id/). Change the numbers here only; the
formulas live in apps/payment_aggregator/fees.py.
"""

from decimal import Decimal

from apps.payment_aggregator.base import FeeType, PaymentMethod

PROVIDER_NAME = "rintisan"

BASE_URL_SANDBOX = "https://api.sandbox.rintisan.co.id/api/v1/billing/payin/partner"
BASE_URL_PRODUCTION = "https://api.rintisan.co.id/api/v1/billing/payin/partner"

# --- Fees (IDR / percent) -------------------------------------------------

# Virtual Account MDR, flat per transaction ("mulai dari Rp5.000", negotiable
# above 1000 trx/month). Paid by the parent on top of the invoice total.
MDR_VA = Decimal("5000")

# Online Credit Card Rintisan MDR, percent. Paid by the parent via gross-up.
MDR_CC = Decimal("2")

# E-commerce MDR, percent. Paid by the parent via gross-up.
MDR_TOKOPEDIA_CC = Decimal("1.75")
MDR_TOKOPEDIA_NON_CC = Decimal("0.5")
MDR_BLIBLI_CC = Decimal("1.75")

# Rintisan's own fee per disbursement (incl. bank validator).
DISBURSEMENT_FEE = Decimal("2500")

# Fee Classping charges the branch per withdrawal, deducted from the
# withdrawn amount. Covers DISBURSEMENT_FEE.
WITHDRAWAL_FEE = Decimal("2500")

# --- Pay-in channels ------------------------------------------------------
# QRIS is intentionally not offered (BI forbids charging QRIS MDR to the payer).
# VAPERMATA is not in the pricing deck; it uses MDR_VA until Rintisan confirms.
# min/max apply to the amount the payer pays (after fee). None = no limit.

VA_MIN_AMOUNT = Decimal("10000")
CC_MIN_AMOUNT = Decimal("10000")
CC_MAX_AMOUNT = Decimal("100000000")  # Rintisan /create limit for CC
E_COMMERCE_MIN_AMOUNT = Decimal("10000")

CHANNELS = {
    "VABCA": {
        "name": "BCA Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
        "fee": MDR_VA,
        "min_amount": VA_MIN_AMOUNT,
        "max_amount": None,
    },
    "VABRI": {
        "name": "BRI Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
        "fee": MDR_VA,
        "min_amount": VA_MIN_AMOUNT,
        "max_amount": None,
    },
    "VAMANDIRI": {
        "name": "Mandiri Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
        "fee": MDR_VA,
        "min_amount": VA_MIN_AMOUNT,
        "max_amount": None,
    },
    "VABNI": {
        "name": "BNI Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
        "fee": MDR_VA,
        "min_amount": VA_MIN_AMOUNT,
        "max_amount": None,
    },
    "VAPERMATA": {
        "name": "Permata Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
        "fee": MDR_VA,
        "min_amount": VA_MIN_AMOUNT,
        "max_amount": None,
    },
    "CC": {
        "name": "Kartu Kredit",
        "method": PaymentMethod.CREDIT_CARD,
        "fee_type": FeeType.PERCENT,
        "fee": MDR_CC,
        "min_amount": CC_MIN_AMOUNT,
        "max_amount": CC_MAX_AMOUNT,
    },
    "TOKOPEDIA CC": {
        "name": "Tokopedia (Kartu Kredit)",
        "method": PaymentMethod.E_COMMERCE,
        "fee_type": FeeType.PERCENT,
        "fee": MDR_TOKOPEDIA_CC,
        "min_amount": E_COMMERCE_MIN_AMOUNT,
        "max_amount": None,
    },
    "TOKOPEDIA NON CC": {
        "name": "Tokopedia",
        "method": PaymentMethod.E_COMMERCE,
        "fee_type": FeeType.PERCENT,
        "fee": MDR_TOKOPEDIA_NON_CC,
        "min_amount": E_COMMERCE_MIN_AMOUNT,
        "max_amount": None,
    },
    "BLIBLI CC": {
        "name": "Blibli (Kartu Kredit)",
        "method": PaymentMethod.E_COMMERCE,
        "fee_type": FeeType.PERCENT,
        "fee": MDR_BLIBLI_CC,
        "min_amount": E_COMMERCE_MIN_AMOUNT,
        "max_amount": None,
    },
}

# --- Pay-in rules ---------------------------------------------------------

# Sent as to_email on every billing instead of the guardian's email, so payers
# never receive emails from Rintisan (all emails come from Classping).
# Overridable with env RINTISAN_PAYER_EMAIL.
PAYER_EMAIL = "no-reply@hamanto.com"

# to_phone must be an Indonesian number, "62" + digits (Rintisan OpenAPI).
# Callers pass a number already normalized by apps.core.phone.
PAYER_PHONE_PATTERN = r"^62[1-9][0-9]{6,20}$"

# Billing expiry. Rintisan expires the billing at the requested time and sends
# the expiry to the payment callback URL; /querypayment then returns EXPIRED.
# Field name / format in /create are NOT in the OpenAPI v1.0.0 yet: set
# BILLING_EXPIRY_FIELD once Rintisan confirms them (None = not sent; only
# deadline_date, the WIB date of expires_at, is sent).
BILLING_EXPIRY_FIELD = None
BILLING_EXPIRY_FORMAT = "%Y-%m-%d %H:%M:%S"  # WIB

# --- Payout limits --------------------------------------------------------

# Per-disbursement limits from Rintisan (apply to the transferred amount).
DISBURSEMENT_MIN_AMOUNT = Decimal("20000")
DISBURSEMENT_MAX_AMOUNT = Decimal("250000000")

# Limits on the amount the branch withdraws (before WITHDRAWAL_FEE is
# deducted), so that transfer_amount stays within the disbursement limits.
WITHDRAWAL_MIN_AMOUNT = DISBURSEMENT_MIN_AMOUNT + WITHDRAWAL_FEE  # 22.500
WITHDRAWAL_MAX_AMOUNT = DISBURSEMENT_MAX_AMOUNT + WITHDRAWAL_FEE  # 250.002.500

# Bank codes accepted for payout accounts (banks only; Rintisan e-wallet codes
# GOPAY/OVO/DANA/SHOPEEPAY/LINKAJA are intentionally excluded).
BANK_CODES = {
    "BCA": "BCA",
    "BNI": "BNI",
    "BRI": "BRI",
    "MANDIRI": "Bank Mandiri",
    "CIMB": "CIMB Niaga",
    "SEABANK": "SeaBank",
    "UOB": "UOB Indonesia",
    "OCBC": "OCBC",
    "DBS": "DBS Indonesia",
    "MAYBANK": "Maybank Indonesia",
    "MASPION": "Bank Maspion",
    "STANCAR": "Standard Chartered",
    "PERMATA": "Bank Permata",
    "MAYAPADA": "Bank Mayapada",
    "MEGA_SYR": "Bank Mega Syariah",
    "ARTHA": "Bank Artha Graha",
    "BCASYARIAH": "BCA Syariah",
    "DANAMON": "Bank Danamon",
    "BSI": "Bank Syariah Indonesia",
    "MEGA": "Bank Mega",
    "SINARMAS": "Bank Sinarmas",
    "JAGO": "Bank Jago",
    "BNC": "Bank Neo Commerce",
    "SAHABAT_SAMPOERNA": "Bank Sahabat Sampoerna",
    "BCA_DIGITAL": "BCA Digital (blu)",
    "BISNIS_INTERNASIONAL": "Bank Bisnis Internasional",
    "INA_PERDANA": "Bank Ina Perdana",
    "ALLO": "Allo Bank",
    "HANA": "Bank KEB Hana",
    "NOBU": "Nobu Bank",
    "BTPN": "BTPN",
}

# --- Protocol -------------------------------------------------------------

REQUEST_TIMEOUT_SECONDS = 15

RESPONSE_CODE_SUCCESS = "200"
RESPONSE_CODE_DUPLICATE = "409"

PAYMENT_STATUS_PAID = "PAID"
PAYMENT_STATUS_EXPIRED = "EXPIRED"
# Expiry callback: same URL as payments. status.code to be confirmed by
# Rintisan; status.message "expired" is matched meanwhile.
CALLBACK_STATUS_EXPIRED_CODES = ()
CALLBACK_STATUS_EXPIRED_MESSAGE = "expired"
DISBURSE_STATUS_DISBURSED = "DISBURSED"

# Payment callback status.code
CALLBACK_STATUS_SUCCESS = "200"

# Disbursement status.code
DISBURSEMENT_STATUS_SUCCESS = "200"
DISBURSEMENT_STATUS_PROCESSING = ("201", "202", "203")
DISBURSEMENT_STATUS_SUSPECT_ACCOUNT = "204"
DISBURSEMENT_STATUS_FAILED = "400"

# Business-error messages returned with response_code "400"
MESSAGE_INSUFFICIENT_BALANCE = "insufficient balance"
MESSAGE_DUPLICATE_REFERENCE = "duplicate reference id"
MESSAGE_INVALID_ACCOUNT = "invalid account number"
MESSAGE_INVALID_BANK = "invalid bank code"
MESSAGE_MIN_AMOUNT = "minimum disbursement amount"
MESSAGE_MAX_AMOUNT = "maximum disbursement amount"
MESSAGE_TRANSACTION_NOT_FOUND = "transaction not found"
MESSAGE_DISBURSEMENT_NOT_FOUND = "disbursement not found"

# Rintisan timestamps ("2026-07-08 10:35:12") are in WIB (UTC+7, no DST).
PROVIDER_UTC_OFFSET_HOURS = 7
PROVIDER_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
