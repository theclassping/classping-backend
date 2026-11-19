"""
What a subscriber may do right now. The only API host code needs:

    has(subscriber, "payment_gateway")                       -> bool
    state(subscriber, "storage_bytes")                       -> "active" | "read_only" | "off"
    limit(subscriber, "max_students")                        -> int | None (None = unlimited)
    check_limit(subscriber, "max_students", used, adding)    -> None, or raises FeatureLocked / LimitReached
    consume(subscriber, "sms_credits", 1, idempotency_key)   -> remaining (metered features)
    summary(subscriber)                                      -> dict for APIs and admin pages

value = override if one exists, else plan value combined with active add-ons
        (boolean: OR, limit: plan + value x quantity, None = unlimited wins).
state = off        feature not in plan / add-ons / overrides, or no subscription
        active     trialing / active / past_due, or ended and feature.on_expiry = keep
        read_only  ended (expired / canceled) and feature.on_expiry = lock
"""
import datetime
from typing import Any, Dict, Optional

from django.core.cache import caches
from django.db.models import Q, Sum
from django.utils import timezone

from . import conf
from .exceptions import FeatureLocked, LimitReached
from .models import AddOnFeature, Feature, FeatureOverride, Subscription, SubscriptionAddOn, UsageRecord
from .status import LIVE, boundaries, effective_plan, effective_status

ACTIVE = "active"
READ_ONLY = "read_only"
OFF = "off"

_VERSION_KEY = "plan_subs:ent:version"


def _cache():
    return caches[conf.get("CACHE_ALIAS")]


def _pk(subscriber):
    return getattr(subscriber, "pk", subscriber)


def _version():
    try:
        return _cache().get(_VERSION_KEY) or 0
    except Exception:
        return 0


def _key(subscriber_id):
    return f"plan_subs:ent:{_version()}:{subscriber_id}"


def invalidate(subscriber):
    try:
        _cache().delete(_key(_pk(subscriber)))
    except Exception:
        pass


def invalidate_all():
    """After a catalog change (plan limits, add-on sizes, features)."""
    try:
        cache = _cache()
        try:
            cache.incr(_VERSION_KEY)
        except ValueError:
            cache.set(_VERSION_KEY, 1, None)
    except Exception:
        pass


def _combine(feature, current, value, mode, quantity):
    """Add one add-on purchase to ``current`` (a bounded limit or a boolean)."""
    if feature.kind == Feature.Kind.BOOLEAN:
        return bool(current) or bool(value)
    if value is None:
        return None  # unlimited wins
    if mode == AddOnFeature.Mode.INCREMENT:
        return current + value * quantity
    return max(current, value)  # grant on a limit: the larger value


def resolve(subscriber, now=None) -> Dict[str, Any]:
    """Compute entitlements without the cache."""
    now = now or timezone.now()
    features = {f.code: f for f in Feature.objects.filter(is_active=True)}
    sub = (
        Subscription.objects.select_related("plan", "price__plan", "pending_price__plan")
        .filter(subscriber_id=_pk(subscriber))
        .first()
    )
    result = {
        "status": None,
        "plan": None,
        "plan_name": None,
        "valid_until": None,
        "features": {code: {"state": OFF, "value": None, "kind": f.kind} for code, f in features.items()},
    }
    if sub is None:
        return result

    status = effective_status(sub, now)
    plan = effective_plan(sub, now)
    values = {}
    for pf in plan.plan_features.select_related("feature"):
        if pf.feature.code in features:
            values[pf.feature.code] = pf.value

    purchases = (
        SubscriptionAddOn.objects.filter(
            subscription=sub,
            status__in=(SubscriptionAddOn.Status.ACTIVE, SubscriptionAddOn.Status.ENDING),
        )
        .filter(Q(started_at__isnull=True) | Q(started_at__lte=now))
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .select_related("addon")
    )
    ends = []
    for purchase in purchases:
        if purchase.ends_at:
            ends.append(purchase.ends_at)
        for af in purchase.addon.addon_features.select_related("feature"):
            feature = features.get(af.feature.code)
            if feature is None:
                continue
            if af.feature.code in values:
                current = values[af.feature.code]
                if current is None and feature.kind != Feature.Kind.BOOLEAN:
                    continue  # already unlimited
            else:
                current = False if feature.kind == Feature.Kind.BOOLEAN else 0
            values[af.feature.code] = _combine(feature, current, af.value, af.mode, purchase.quantity)

    overrides = FeatureOverride.objects.filter(subscriber_id=sub.subscriber_id).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).select_related("feature")
    for override in overrides:
        if override.feature.code in features:
            values[override.feature.code] = override.value
            if override.expires_at:
                ends.append(override.expires_at)

    for code, feature in features.items():
        if code not in values:
            continue
        if status in LIVE or feature.on_expiry == Feature.OnExpiry.KEEP:
            state_ = ACTIVE
        else:
            state_ = READ_ONLY
        result["features"][code] = {"state": state_, "value": values[code], "kind": feature.kind}

    upcoming = [b for b in boundaries(sub) + ends if b > now]
    result.update(
        status=status,
        plan=plan.code,
        plan_name=plan.name,
        subscription_id=sub.pk,
        valid_until=min(upcoming).isoformat() if upcoming else None,
    )
    return result


def summary(subscriber, now=None) -> Dict[str, Any]:
    """Cached entitlements. The entry never outlives the next deadline."""
    if now is not None:
        return resolve(subscriber, now)
    key = _key(_pk(subscriber))
    cache = _cache()
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    current = timezone.now()
    if cached is not None:
        valid_until = cached.get("valid_until")
        if not valid_until or datetime.datetime.fromisoformat(valid_until) > current:
            return cached
    result = resolve(subscriber, current)
    ttl = int(conf.get("CACHE_TTL"))
    if result.get("valid_until"):
        seconds = (datetime.datetime.fromisoformat(result["valid_until"]) - current).total_seconds()
        ttl = max(1, min(ttl, int(seconds)))
    try:
        cache.set(key, result, ttl)
    except Exception:
        pass
    return result


def _feature(subscriber, code, now=None):
    return summary(subscriber, now)["features"].get(code, {"state": OFF, "value": None, "kind": None})


def state(subscriber, code, now=None) -> str:
    return _feature(subscriber, code, now)["state"]


def has(subscriber, code, now=None) -> bool:
    entry = _feature(subscriber, code, now)
    return entry["state"] == ACTIVE and bool(entry["value"])


def limit(subscriber, code, now=None) -> Optional[int]:
    """The limit when the feature is active; 0 when off or read-only; None = unlimited."""
    entry = _feature(subscriber, code, now)
    if entry["state"] != ACTIVE:
        return 0
    return entry["value"]


def raw_limit(subscriber, code, now=None) -> Optional[int]:
    """The limit whatever the state (for showing "used / limit" after expiry)."""
    entry = _feature(subscriber, code, now)
    if entry["state"] == OFF:
        return 0
    return entry["value"]


def check_limit(subscriber, code, used, adding=1, now=None) -> None:
    """Raise unless ``used + adding`` fits. Removing (adding <= 0) is always allowed."""
    if adding <= 0:
        return
    entry = _feature(subscriber, code, now)
    if entry["state"] != ACTIVE:
        raise FeatureLocked(code, entry["state"])
    value = entry["value"]
    if value is None:
        return
    if entry["kind"] == Feature.Kind.BOOLEAN:
        if not value:
            raise FeatureLocked(code, OFF)
        return
    if used + adding > value:
        raise LimitReached(code, value, used, adding)


def _period_start(feature, now):
    if feature.reset_period == Feature.ResetPeriod.MONTHLY:
        return timezone.localtime(now).date().replace(day=1)
    return datetime.date(1970, 1, 1)


def consume(subscriber, code, quantity, idempotency_key, now=None) -> Optional[int]:
    """Record metered usage; returns what is left (None = unlimited)."""
    now = now or timezone.now()
    feature = Feature.objects.get(code=code)
    period_start = _period_start(feature, now)
    existing = UsageRecord.objects.filter(idempotency_key=idempotency_key).first()
    used = (
        UsageRecord.objects.filter(subscriber_id=_pk(subscriber), feature=feature, period_start=period_start)
        .aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    value = limit(subscriber, code, now)
    if existing is None:
        check_limit(subscriber, code, used, quantity, now)
        UsageRecord.objects.create(
            subscriber_id=_pk(subscriber), feature=feature, quantity=quantity,
            period_start=period_start, idempotency_key=idempotency_key,
        )
        used += quantity
    return None if value is None else max(0, value - used)
