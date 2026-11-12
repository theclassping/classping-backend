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
    "NETWORK_PAY_PG_CARD": {
        "name": "Kartu Kredit/Debit",
        "pay_method": "NETWORK_PAY",
        "method": PaymentMethod.CREDIT_CARD,
        "fee_type": FeeType.PERCENT,
    },
}

# Channels whose payOptionDetails need additionalInfo.phoneNumber.
PHONE_REQUIRED_PAY_METHODS = ("NETWORK_PAY",)

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

# Acknowledgements we send back to DANA's notifications.
ACK_FINISH_NOTIFY = {"responseCode": "2005600", "responseMessage": "Successful"}
ACK_TRANSFER_NOTIFY = {"responseCode": "2004300", "responseMessage": "Successful"}

# latestTransactionStatus. "02" = paying, payment is success (DANA: mark Success).
STATUS_PAID = ("00", "02")
STATUS_NOT_FOUND = "07"

# Response code prefixes meaning "outcome unknown, retry" (DANA: mark Pending).
RETRYABLE_PREFIXES = ("202", "429")
RETRYABLE_CODES = ("5005401", "5005501")

ORDER_TITLE_MAX = 64
PHONE_MAX = 15

# DANA timestamps: "2026-11-12T10:30:00+07:00" (WIB).
PROVIDER_UTC_OFFSET_HOURS = 7
