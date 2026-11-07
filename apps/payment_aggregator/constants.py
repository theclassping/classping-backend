"""
Provider selection for the payment aggregator.

Fee amounts, channels and limits are NOT defined here: each provider keeps
its own numbers in ``providers/<name>/constants.py``.
"""

# Active provider key (see PROVIDER_CLASSES).
PAYMENT_AGGREGATOR_PROVIDER = "rintisan"

PROVIDER_CLASSES = {
    "rintisan": "apps.payment_aggregator.providers.rintisan.provider.RintisanProvider",
}
