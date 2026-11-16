"""
DOKU channels and protocol constants: DOKU Checkout (pay-in, Non-SNAP) and
Kirim DOKU (payout, SNAP).

Source: https://developers.doku.com (index: /llms.txt), read 2026-11-15.
Contract rates are not here: the application passes them to
DokuProvider(channel_fees=..., channel_flat_fees=...).
"""

from payment_aggregator.base import FeeType, PaymentMethod

PROVIDER_NAME = "doku"

BASE_URL_SANDBOX = "https://api-sandbox.doku.com"
BASE_URL_PRODUCTION = "https://api.doku.com"

# --- Pay-in: DOKU Checkout (Non-SNAP, HMAC-SHA256) -----------------------

PATH_CHECKOUT = "/checkout/v1/payment"
PATH_ORDER_STATUS = "/orders/v1/status/{invoice_number}"

# Checkout payment_method_types. One value per order: DOKU then skips its
# method picker and opens that channel directly, so the channel (and the fee
# the parent pays on top) is known before the order is created.
# QRIS is intentionally not listed (BI forbids charging QRIS MDR to the payer).
CHANNELS = {
    "VIRTUAL_ACCOUNT_BCA": {
        "name": "BCA Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_BNI": {
        "name": "BNI Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_BRI": {
        "name": "BRI Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_BANK_MANDIRI": {
        "name": "Mandiri Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_BANK_PERMATA": {
        "name": "Permata Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_BANK_CIMB": {
        "name": "CIMB Niaga Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_BANK_DANAMON": {
        "name": "Danamon Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    "VIRTUAL_ACCOUNT_BANK_SYARIAH_MANDIRI": {
        "name": "BSI Virtual Account",
        "method": PaymentMethod.VIRTUAL_ACCOUNT,
        "fee_type": FeeType.FLAT,
    },
    # E-wallets (percent). The payer finishes on DOKU's page (OVO asks for
    # the phone number there); FAILED / TIMEOUT stay pending on our side.
    "EMONEY_DANA": {
        "name": "DANA",
        "method": PaymentMethod.E_WALLET,
        "fee_type": FeeType.PERCENT,
    },
    "EMONEY_DOKU": {
        "name": "DOKU Wallet",
        "method": PaymentMethod.E_WALLET,
        "fee_type": FeeType.PERCENT,
    },
    "EMONEY_OVO": {
        "name": "OVO",
        "method": PaymentMethod.E_WALLET,
        "fee_type": FeeType.PERCENT,
    },
    "EMONEY_SHOPEE_PAY": {
        "name": "ShopeePay",
        "method": PaymentMethod.E_WALLET,
        "fee_type": FeeType.PERCENT,
    },
    "EMONEY_LINKAJA": {
        "name": "LinkAja",
        "method": PaymentMethod.E_WALLET,
        "fee_type": FeeType.PERCENT,
    },
    # Percent + flat (channel_flat_fees): Visa/Mastercard/JCB 2.8% + Rp2.000.
    "CREDIT_CARD": {
        "name": "Kartu Kredit/Debit",
        "method": PaymentMethod.CREDIT_CARD,
        "fee_type": FeeType.PERCENT,
    },
}

# order.invoice_number: max 64, but 30 when the Credit Card channel is active.
INVOICE_NUMBER_MAX = 30
CUSTOMER_NAME_MAX = 255
CUSTOMER_PHONE_MAX = 16
# payment.payment_due_date, in minutes (max 6 digits).
PAYMENT_DUE_MINUTES_MIN = 1
PAYMENT_DUE_MINUTES_MAX = 999999

# transaction.status (notification and Check Status). Only SUCCESS is final
# and paid. With Checkout, FAILED must be ignored (the payer may retry);
# EXPIRED stays pending here because expiry is an application rule.
TRANSACTION_SUCCESS = "SUCCESS"

# --- Payout: Kirim DOKU (SNAP, B2B token + HMAC-SHA512) -------------------

PATH_ACCESS_TOKEN = "/authorization/v1/access-token/b2b"
PATH_ACCOUNT_INQUIRY = "/snap/v1.1/emoney/bank-account-inquiry"
PATH_TRANSFER_BANK = "/snap/v1.1/emoney/transfer-bank"
PATH_TRANSFER_STATUS = "/snap/v1.1/qr/qr-mpm-status"  # Kirim DOKU Check Status
PATH_BALANCE_INQUIRY = "/snap/v1.1/balance-inquiry"

# CHANNEL-ID header. DOKU does not publish a value for Kirim DOKU;
# override with DOKU_PAYOUT_CHANNEL_ID if DOKU gives another one.
DEFAULT_CHANNEL_ID = "H2H"
CURRENCY = "IDR"
SENDER_COUNTRY_CODE = "ID"
DEFAULT_SENDER_ID_TYPE = "KTP"

# additionalInfo.channelCode: "07" bank deposit (online), "11" BI-FAST.
# Empty = not sent (DOKU's default routing; the sandbox test cases need 07
# or no value).
CHANNEL_CODE_BANK_DEPOSIT = "07"
CHANNEL_CODE_BI_FAST = "11"

# serviceCode of Transfer Bank, sent to Check Status.
SERVICE_CODE_TRANSFER = "43"

# Access token: valid 900 s; renewed this many seconds early.
TOKEN_REFRESH_MARGIN_SECONDS = 60

RESPONSE_TOKEN_SUCCESS = "2007300"
RESPONSE_INQUIRY_SUCCESS = "2004200"
RESPONSE_TRANSFER_SUCCESS = "2004300"  # PAID
RESPONSE_TRANSFER_PENDING = "2024300"  # UNPAID: settled by notification / T+1
RESPONSE_STATUS_SUCCESS = "2005300"
RESPONSE_STATUS_NOT_FOUND = "4045301"
RESPONSE_BALANCE_SUCCESS = "2001100"

# Transfer Bank business errors (the transfer was not made).
TRANSFER_INSUFFICIENT_FUNDS = ("4034314",)
TRANSFER_INVALID_ACCOUNT = ("4034305", "4034309", "4034318", "4044311", "4044303")
TRANSFER_DUPLICATE = ("4094301", "4094302")
# Account Inquiry: beneficiary account invalid / bank not supported.
INQUIRY_INVALID_ACCOUNT = ("4044211", "4044203")

# Check Status latestTransactionStatus.
TRANSFER_STATUS_SUCCESS = "00"
TRANSFER_STATUS_PENDING = "03"
TRANSFER_STATUS_REFUNDED = "04"
TRANSFER_STATUS_FAILED = "06"

# Unpaid / Refund notification transactionStatus.
NOTIFY_STATUS_SUCCESS = "50"
NOTIFY_STATUS_FAILED = "35"
NOTIFY_STATUS_UNPAID = "20"
NOTIFY_STATUS_REFUNDED = "40"

# Reply Kirim DOKU expects to a processed notification (plus transactionId).
NOTIFY_ACK = {"responseCode": "00", "responseMessage": "Successfully processed", "status": True}

ACCOUNT_NAME_MAX = 64
REMARK_MAX = 255

# Classping bank codes (shared by every provider, as stored on payout
# accounts) -> (DOKU bank ID = BI code, display name). All are on DOKU's
# supported-bank list with Online and BI-FAST routes.
BANKS = {
    "BCA": ("014", "BCA"),
    "BNI": ("009", "BNI"),
    "BRI": ("002", "BRI"),
    "MANDIRI": ("008", "Bank Mandiri"),
    "CIMB": ("022", "CIMB Niaga"),
    "SEABANK": ("535", "SeaBank"),
    "UOB": ("023", "UOB Indonesia"),
    "OCBC": ("028", "OCBC"),
    "DBS": ("046", "DBS Indonesia"),
    "MAYBANK": ("016", "Maybank Indonesia"),
    "MASPION": ("157", "Bank Maspion"),
    "STANCAR": ("050", "Standard Chartered"),
    "PERMATA": ("013", "Bank Permata"),
    "MAYAPADA": ("097", "Bank Mayapada"),
    "MEGA_SYR": ("506", "Bank Mega Syariah"),
    "ARTHA": ("037", "Bank Artha Graha"),
    "BCASYARIAH": ("536", "BCA Syariah"),
    "DANAMON": ("011", "Bank Danamon"),
    "BSI": ("451", "Bank Syariah Indonesia"),
    "MEGA": ("426", "Bank Mega"),
    "SINARMAS": ("153", "Bank Sinarmas"),
    "JAGO": ("542", "Bank Jago"),
    "BNC": ("490", "Bank Neo Commerce"),
    "SAHABAT_SAMPOERNA": ("523", "Bank Sahabat Sampoerna"),
    "BCA_DIGITAL": ("501", "BCA Digital (blu)"),
    "BISNIS_INTERNASIONAL": ("459", "Krom Bank (Bisnis Internasional)"),
    "INA_PERDANA": ("513", "Bank Ina Perdana"),
    "ALLO": ("567", "Allo Bank"),
    "HANA": ("484", "Bank KEB Hana"),
    "NOBU": ("503", "Nobu Bank"),
    "BTPN": ("213", "SMBC Indonesia (BTPN)"),
}

# --- Protocol -------------------------------------------------------------

REQUEST_TIMEOUT_SECONDS = 15

# Checkout expired_date "yyyyMMddHHmmss" and Kirim DOKU X-TIMESTAMP are WIB.
PROVIDER_UTC_OFFSET_HOURS = 7
