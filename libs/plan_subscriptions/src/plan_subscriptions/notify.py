"""
Notifications. The package decides *when* (events below); the host decides
*how* (email, push, ...) by setting PLAN_SUBSCRIPTIONS["NOTIFIER"].

Events and their context:
    trial_started      plan, trial_start, trial_end, trial_days
    trial_ending       plan, trial_end, days_left
    invoice_issued     invoice, plan_name
    invoice_reminder   invoice, plan_name, days_left
    payment_overdue    invoice (may be None), days_overdue, grace_ends_at
    expired            plan, expired_at
    payment_received   invoice, plan_name, paid_at, payment (host dict or None)
"""
import contextlib
import logging
import threading

logger = logging.getLogger(__name__)

EVENTS = (
    "trial_started",
    "trial_ending",
    "invoice_issued",
    "invoice_reminder",
    "payment_overdue",
    "expired",
    "payment_received",
)

_state = threading.local()


class Notifier:
    def send(self, event, subscription, context):
        raise NotImplementedError


class NullNotifier(Notifier):
    def send(self, event, subscription, context):
        logger.info("Subscription %s: %s (no notifier configured)", subscription.pk, event)


@contextlib.contextmanager
def notifications_disabled():
    """Nothing is sent inside this block (seeding, data migrations, tests)."""
    previous = getattr(_state, "disabled", False)
    _state.disabled = True
    try:
        yield
    finally:
        _state.disabled = previous


def are_disabled():
    return getattr(_state, "disabled", False)


def send(event, subscription, context=None):
    """True when sent (or deliberately skipped); False when the notifier failed."""
    if are_disabled():
        return True
    from . import conf

    try:
        conf.notifier().send(event, subscription, context or {})
    except Exception:
        logger.exception("Subscription %s: sending %s failed", subscription.pk, event)
        return False
    return True
