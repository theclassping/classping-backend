"""
Effective status from dates.

Enforcement never waits for the scheduled job: every check works out the
status from ``now``. The job (services.advance_statuses) only writes the
same result to the table and sends the emails.
"""
from datetime import timedelta

from . import conf
from .models import Subscription

S = Subscription.Status
LIVE = (S.TRIALING, S.ACTIVE, S.PAST_DUE)
ENDED = (S.EXPIRED, S.CANCELED)


def access_until(sub):
    """Until when access is covered: the trial or the last paid period."""
    candidates = [d for d in (sub.trial_end, sub.paid_through) if d is not None]
    return max(candidates) if candidates else None


def grace_end(sub):
    until = access_until(sub)
    if until is None:
        return None
    return until + timedelta(days=int(conf.get("GRACE_DAYS")))


def effective_status(sub, now):
    if sub.status in ENDED:
        return sub.status
    until = access_until(sub)
    if until is None:
        return S.EXPIRED
    if sub.cancel_at_period_end and now >= until:
        return S.CANCELED
    if now < until:
        if sub.status == S.TRIALING and sub.trial_end and now < sub.trial_end:
            return S.TRIALING
        return S.ACTIVE
    if now < grace_end(sub):
        return S.PAST_DUE
    return S.EXPIRED


def effective_price(sub, now):
    if sub.pending_price_id and sub.pending_from and now >= sub.pending_from:
        return sub.pending_price
    return sub.price


def effective_plan(sub, now):
    return effective_price(sub, now).plan


def boundaries(sub):
    """Moments at which the effective status or plan can change."""
    points = [sub.trial_end, access_until(sub), grace_end(sub), sub.pending_from]
    return [p for p in points if p is not None]
