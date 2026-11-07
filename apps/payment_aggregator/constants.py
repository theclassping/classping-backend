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

# A gateway checkout must be paid within this many minutes. The expiry time is
# sent to the provider with the billing; the provider expires it and notifies
# Classping via the payment callback. After that the invoice is open for
# manual payment again.
PAYMENT_DEADLINE_MINUTES = 60

# Backup to the provider's expiry webhook: a queued job checks the checkout
# this many minutes after expires_at (the webhook usually arrives first).
PAYMENT_EXPIRY_CHECK_DELAY_MINUTES = 2

# One checkout pays 1..N invoices of one student.
MAX_INVOICES_PER_CHECKOUT = 5
