"""Settings with defaults.

Two settings:

* ``PLAN_SUBSCRIPTIONS_SUBSCRIBER_MODEL`` ("app_label.Model"): who subscribes.
  A top-level setting (like AUTH_USER_MODEL) because migrations read it.
* ``PLAN_SUBSCRIPTIONS`` (dict): everything else, see DEFAULTS.
"""
from decimal import Decimal

from django.conf import settings
from django.utils.module_loading import import_string

DEFAULTS = {
    # callable(request) -> subscriber instance or None
    "SUBSCRIBER_RESOLVER": None,
    # callable(subscriber) -> str, shown in admin and emails
    "SUBSCRIBER_LABEL": None,
    # callable(subscriber) -> {feature_code: used}, shown next to limits in the API
    "USAGE_PROVIDER": None,
    "API_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "BILLING_BACKEND": "plan_subscriptions.billing.ManualBilling",
    "NOTIFIER": "plan_subscriptions.notify.NullNotifier",
    "CURRENCY": "IDR",
    # Whole units for IDR; 2 for currencies with cents.
    "AMOUNT_DECIMALS": 0,
    # Added on top of prices; "0" disables.
    "TAX_RATE": "0",
    "TAX_LABEL": "Tax",
    # Trial length when the plan has no trial_days of its own. 0 = no trial.
    "DEFAULT_TRIAL_DAYS": 0,
    # Plan code every trial starts on (None = the plan passed to start_trial).
    "TRIAL_PLAN": None,
    # Days past due (features still on) before read-only.
    "GRACE_DAYS": 7,
    # Renewal / first invoice is issued this many days before the period ends.
    "INVOICE_LEAD_DAYS": 7,
    # Unpaid add-on / upgrade invoices are voided after this many days.
    "PURCHASE_INVOICE_DAYS": 7,
    "TRIAL_REMINDER_DAYS": [30, 7, 1],
    "RENEWAL_REMINDER_DAYS": [1],
    "INVOICE_NUMBER_PREFIX": "INV",
    "CACHE_ALIAS": "default",
    # Upper bound; entries also expire at the next status deadline.
    "CACHE_TTL": 300,
}


def subscriber_model_label():
    return getattr(settings, "PLAN_SUBSCRIPTIONS_SUBSCRIBER_MODEL")


def get(name):
    user = getattr(settings, "PLAN_SUBSCRIPTIONS", {}) or {}
    return user.get(name, DEFAULTS[name])


def tax_rate():
    return Decimal(str(get("TAX_RATE")))


def load(name):
    """Import a dotted-path setting (class or callable); None stays None."""
    value = get(name)
    if value is None or not isinstance(value, str):
        return value
    return import_string(value)


def billing_backend():
    return load("BILLING_BACKEND")()


def notifier():
    return load("NOTIFIER")()


def subscriber_label(subscriber):
    label = load("SUBSCRIBER_LABEL")
    return label(subscriber) if label else str(subscriber)
