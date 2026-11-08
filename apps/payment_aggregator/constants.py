"""
General (provider-independent) payment rules and provider selection.

Fee amounts, channels and limits are NOT defined here: each provider keeps
its own numbers in ``providers/<name>/constants.py``.
"""

# Active provider key (see PROVIDER_CLASSES).
PAYMENT_AGGREGATOR_PROVIDER = "rintisan"

PROVIDER_CLASSES = {
    "rintisan": "apps.payment_aggregator.providers.rintisan.provider.RintisanProvider",
}

# --- Classping rules ------------------------------------------------------

# A gateway checkout must be paid within this many minutes. Only the date
# (deadline_date) is sent to the provider; Classping expires the checkout
# itself after the window, and the invoice is open for manual payment again.
PAYMENT_DEADLINE_MINUTES = 60

# The expiry check runs this many minutes after expires_at (the provider sends
# no expiry callback).
PAYMENT_EXPIRY_CHECK_DELAY_MINUTES = 2

# One checkout pays 1..N invoices of one student.
MAX_INVOICES_PER_CHECKOUT = 5

# Classping takes no fee of its own: the payer pays the provider's
# transaction fee on top, and the branch receives the full invoice total.

# Branch staff (Staff.staff_type) who may cancel a checkout and manage the
# branch wallet / withdrawals.
BRANCH_FINANCE_STAFF_TYPES = ("officer", "principal")

# --- Withdrawals ----------------------------------------------------------

# OTP emailed to the branch before a withdrawal is sent to the provider.
WITHDRAWAL_OTP_LENGTH = 6
WITHDRAWAL_OTP_TTL_MINUTES = 3
WITHDRAWAL_OTP_MAX_ATTEMPTS = 3

# Receives the nightly branch balance check alert (wallets.check_branch_balances).
OPS_ALERT_EMAIL = "the.class.ping@gmail.com"
