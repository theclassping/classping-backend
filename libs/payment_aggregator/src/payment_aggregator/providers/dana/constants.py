"""
DANA channels and protocol constants (Gapura Payment Gateway, Custom Checkout).

Source: DANA API docs v2 (https://dashboard.dana.id/api-docs-v2/), SNAP
asymmetric signature. Contract rates are not here: the application passes them
to DanaProvider(channel_fees=...).
"""

from payment_aggregator.base import FeeType, PaymentMethod

PROVIDER_NAME = "dana"

BASE_URL_SANDBOX = "https://api.sandbox.dana.id"
BASE_URL_PRODUCTION = "https://api.saas.dana.id"

# --- Paths ----------------------------------------------------------------

PATH_CREATE_ORDER = "/payment-gateway/v1.0/debit/payment-host-to-host.htm"
PATH_QUERY_PAYMENT = "/payment-gateway/v1.0/debit/status.htm"
PATH_CANCEL_ORDER = "/payment-gateway/v1.0/debit/cancel.htm"

# Disbursement to Bank (debits the Merchant Disbursement Account, MDA).
PATH_BANK_ACCOUNT_INQUIRY = "/v1.0/emoney/bank-account-inquiry.htm"  # service 42
PATH_TRANSFER_BANK = "/v1.0/emoney/transfer-bank.htm"  # service 43
PATH_TRANSFER_STATUS = "/v1.0/emoney/transfer-bank-status.htm"
PATH_REFUND_ORDER = "/payment-gateway/v1.0/debit/refund.htm"

# SNAP standard paths of OUR notify endpoints. DANA signs a callback over the
# path it calls; the verifier also accepts these in case DANA signs the
# standard path while calling a prefixed URL.
SNAP_PATH_FINISH_NOTIFY = "/v1.0/debit/notify"
SNAP_PATH_TRANSFER_NOTIFY = "/v1.0/debit/emoney/transfer-bank/notify.htm"

# --- Pay-in channels (payOption -> payMethod) ------------------------------
# QRIS is intentionally not listed (BI forbids charging QRIS MDR to the payer).
# No min/max limits are published; None = no limit on our side.

CHANNELS = {
    "VIRTUAL_ACCOUNT_BCA": {
        "name": "BCA Virtual Account",
        "pay_method": "VIRTUAL_ACCOUNT",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_BNI": {
        "name": "BNI Virtual Account",
        "pay_method": "VIRTUAL_ACCOUNT",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_BRI": {
        "name": "BRI Virtual Account",
        "pay_method": "VIRTUAL_ACCOUNT",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_MANDIRI": {
        "name": "Mandiri Virtual Account",
        "pay_method": "VIRTUAL_ACCOUNT",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_PERMATA": {
        "name": "Permata Virtual Account",
        "pay_method": "VIRTUAL_ACCOUNT",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_CIMB": {
        "name": "CIMB Niaga Virtual Account",
        "pay_method": "VIRTUAL_ACCOUNT",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    # Card: payMethod CREDIT_CARD (DEBIT_CARD also accepted) with payOption
    # NETWORK_PAY_PG_CARD (DANA integration team, 2026-11-16); the card input
    # page is DANA's webRedirectUrl.
    "NETWORK_PAY_PG_CARD": {
        "name": "Kartu Kredit/Debit",
        "pay_method": "CREDIT_CARD",
        "method": PaymentMethod.CREDIT_CARD,
        "fee_type": FeeType.PERCENT,
    },
    # E-wallets (payOption values from DANA's Consult Pay / Create Order docs).
    "NETWORK_PAY_PG_OVO": {
        "name": "OVO",
        "pay_method": "NETWORK_PAY",
        "method": PaymentMethod.E_WALLET,
        "fee_type": FeeType.PERCENT,
    },
    "NETWORK_PAY_PG_GOPAY": {
        "name": "GoPay",
        "pay_method": "NETWORK_PAY",
        "method": PaymentMethod.E_WALLET,
        "fee_type": FeeType.PERCENT,
    },
    "NETWORK_PAY_PG_SPAY": {
        "name": "ShopeePay",
        "pay_method": "NETWORK_PAY",
        "method": PaymentMethod.E_WALLET,
        "fee_type": FeeType.PERCENT,
    },
    "NETWORK_PAY_PG_LINKAJA": {
        "name": "LinkAja",
        "pay_method": "NETWORK_PAY",
        "method": PaymentMethod.E_WALLET,
        "fee_type": FeeType.PERCENT,
    },
}

# Channels whose payOptionDetails need additionalInfo.phoneNumber.
PHONE_REQUIRED_PAY_METHODS = ("NETWORK_PAY", "CREDIT_CARD")

# --- Protocol -------------------------------------------------------------

REQUEST_TIMEOUT_SECONDS = 15

# CHANNEL-ID header. Not a per-merchant credential: DANA's official SDKs and
# every documentation sample send this fixed value.
DEFAULT_CHANNEL_ID = "95221"
CURRENCY = "IDR"

# Create Order (service 54)
SERVICE_CODE_PAYMENT = "54"
RESPONSE_CREATE_SUCCESS = "2005400"
RESPONSE_CREATE_INCONSISTENT = "4045418"

# Query Payment (service 55)
RESPONSE_QUERY_SUCCESS = "2005500"
RESPONSE_QUERY_NOT_FOUND = "4045501"

# Cancel Order (service 57): unpaid orders, or paid ones within 24 hours.
RESPONSE_CANCEL_SUCCESS = "2005700"
RESPONSE_CANCEL_NOT_FOUND = "4045701"
# Expired cancel window / status that does not allow cancelling (e.g. paid).
RESPONSE_CANCEL_NOT_ALLOWED = ("4035700", "4045700")

# Refund Order (service 58). partnerRefundNo makes a retry idempotent.
RESPONSE_REFUND_SUCCESS = "2005800"
# Same partnerRefundNo with different content: investigate, never resend blindly.
RESPONSE_REFUND_INCONSISTENT = "4045818"
# Who asks for the refund (additionalInfo.actorContext, required).
REFUND_ACTOR_TYPE = "MERCHANT"

# --- Disbursement to Bank ---------------------------------------------------

FUND_TYPE_BANK = "MERCHANT_WITHDRAW_FOR_CORPORATE"
# Who bears DANA's transfer charge: the merchant (billed to the MDA), so the
# bank account receives exactly the amount sent.
CHARGE_TARGET = "MERCHANT"

RESPONSE_INQUIRY_SUCCESS = "2004200"
# Bank account invalid / blacklisted.
RESPONSE_INQUIRY_INVALID_ACCOUNT = ("4044211",)
RESPONSE_INQUIRY_INSUFFICIENT = "4034214"

RESPONSE_TRANSFER_SUCCESS = "2004300"
RESPONSE_TRANSFER_IN_PROGRESS = "2024300"
RESPONSE_TRANSFER_INSUFFICIENT = "4034314"  # MDA balance too low: top it up
RESPONSE_TRANSFER_INVALID_ACCOUNT = ("4044303", "4044311")  # bank unsupported / account invalid
# Same partnerReferenceNo, other content: DANA says treat as done and check.
RESPONSE_TRANSFER_INCONSISTENT = "4044318"

# Transfer status inquiry (serviceCode always "00").
SERVICE_CODE_TRANSFER_STATUS = "00"
RESPONSE_TRANSFER_STATUS_SUCCESS = "2000000"
RESPONSE_TRANSFER_STATUS_NOT_FOUND = "4040001"
TRANSFER_STATUS_SUCCESS = ("00",)
TRANSFER_STATUS_PROCESSING = ("01", "02", "03")
TRANSFER_STATUS_FAILED = ("04", "05", "06")
TRANSFER_STATUS_NOT_FOUND = "07"

ACCOUNT_NAME_MAX = 64

# Acknowledgements we send back to DANA's notifications.
ACK_FINISH_NOTIFY = {"responseCode": "2005600", "responseMessage": "Successful"}
ACK_TRANSFER_NOTIFY = {"responseCode": "2004300", "responseMessage": "Successful"}

# latestTransactionStatus. "02" = paying, payment is success (DANA: mark Success).
STATUS_PAID = ("00", "02")
STATUS_NOT_FOUND = "07"

# Response code prefixes meaning "outcome unknown, retry" (DANA: mark Pending).
RETRYABLE_PREFIXES = ("202", "429")
RETRYABLE_CODES = ("5005401", "5005501", "5005701", "5005801", "5004301", "5000001")

ORDER_TITLE_MAX = 64
PHONE_MAX = 15

# DANA timestamps: "2026-11-12T10:30:00+07:00" (WIB).
PROVIDER_UTC_OFFSET_HOURS = 7
