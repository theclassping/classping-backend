"""
Catalog: load a host's features, plans and add-ons, and edit them safely.

load_catalog(data) only creates what is missing (matched by code). It never
overwrites values an admin changed later, so it is safe in a data migration
and in seed commands that run again.

    {
        "features": [{"code", "name", "kind", "unit"?, "on_expiry"?, "reset_period"?}],
        "plans": [{"code", "name", "sort_order"?, "is_public"?, "trial_days"?, "description"?,
                   "prices": [{"interval", "amount", "interval_count"?}],
                   "features": {feature_code: value}}],
        "addons": [{"code", "name", "billing", "price", "max_quantity"?, "plans"?: [plan codes],
                    "features": [{"feature", "value", "mode"?}]}],
    }
"""
from decimal import Decimal

from django.db import transaction

from . import entitlements
from .models import AddOn, AddOnFeature, CatalogChange, Feature, Plan, PlanFeature, PlanPrice, Subscription


def load_catalog(data, models=None, currency="IDR"):
    """``models``: pass ``apps.get_model`` inside a data migration."""
    get = models or {
        "Feature": Feature, "Plan": Plan, "PlanPrice": PlanPrice, "PlanFeature": PlanFeature,
        "AddOn": AddOn, "AddOnFeature": AddOnFeature,
    }.__getitem__
    FeatureM, PlanM, PriceM, PlanFeatureM = get("Feature"), get("Plan"), get("PlanPrice"), get("PlanFeature")
    AddOnM, AddOnFeatureM = get("AddOn"), get("AddOnFeature")
    created = {"features": 0, "plans": 0, "addons": 0}
    with transaction.atomic():
        features = {}
        for order, item in enumerate(data.get("features", [])):
            item = dict(item)
            code = item.pop("code")
            item.setdefault("sort_order", order)
            feature, made = FeatureM.objects.get_or_create(code=code, defaults=item)
            features[code] = feature
            created["features"] += made
        for item in data.get("plans", []):
            item = dict(item)
            code = item.pop("code")
            prices = item.pop("prices", [])
            values = item.pop("features", {})
            plan, made = PlanM.objects.get_or_create(code=code, defaults=item)
            created["plans"] += made
            if made:
                for price in prices:
                    PriceM.objects.create(
                        plan=plan, interval=price.get("interval", "month"),
                        interval_count=price.get("interval_count", 1),
                        amount=Decimal(str(price["amount"])), currency=price.get("currency", currency),
                    )
            for feature_code, value in values.items():
                feature = features.get(feature_code) or FeatureM.objects.get(code=feature_code)
                PlanFeatureM.objects.get_or_create(plan=plan, feature=feature, defaults={"value": value})
        for item in data.get("addons", []):
            item = dict(item)
            code = item.pop("code")
            values = item.pop("features", [])
            plan_codes = item.pop("plans", [])
            item["price"] = Decimal(str(item["price"]))
            item.setdefault("currency", currency)
            addon, made = AddOnM.objects.get_or_create(code=code, defaults=item)
            created["addons"] += made
            if made:
                if plan_codes:
                    addon.plans.set(PlanM.objects.filter(code__in=plan_codes))
                for value in values:
                    feature = features.get(value["feature"]) or FeatureM.objects.get(code=value["feature"])
                    AddOnFeatureM.objects.get_or_create(
                        addon=addon, feature=feature,
                        defaults={"value": value["value"], "mode": value.get("mode", "increment")},
                    )
    return created


def _log(object_type, obj, action, changes, actor):
    CatalogChange.objects.create(
        object_type=object_type, object_id=obj.pk, action=action, changes=changes,
        actor=actor if getattr(actor, "pk", None) else None,
    )


def set_plan_price(plan, amount, actor=None, interval="month", apply_to_existing=False):
    """A new price row. Existing subscribers keep theirs unless apply_to_existing.

    apply_to_existing moves them to the new price from their next invoice."""
    amount = Decimal(str(amount))
    with transaction.atomic():
        current = plan.current_price(interval)
        if current is not None and current.amount == amount:
            return current
        price = PlanPrice.objects.create(
            plan=plan, interval=interval, amount=amount, currency=current.currency if current else "IDR",
        )
        PlanPrice.objects.filter(plan=plan, interval=interval, is_active=True).exclude(pk=price.pk).update(is_active=False)
        moved = 0
        if apply_to_existing and current is not None:
            moved = Subscription.objects.filter(price__plan=plan).exclude(price=price).update(price=price)
            Subscription.objects.filter(pending_price__plan=plan).update(pending_price=price)
        _log("plan", plan, "price_changed", {
            "from": str(current.amount) if current else None, "to": str(amount),
            "apply_to_existing": apply_to_existing, "moved": moved,
        }, actor)
    return price


def set_plan_feature(plan, feature, value, actor=None):
    """Applies to every subscriber of the plan immediately."""
    with transaction.atomic():
        row = PlanFeature.objects.filter(plan=plan, feature=feature).first()
        before = row.value if row else "(not included)"
        if row is None:
            PlanFeature.objects.create(plan=plan, feature=feature, value=value)
        elif row.value != value:
            row.value = value
            row.save(update_fields=["value"])
        else:
            return
        _log("plan", plan, "feature_changed", {"feature": feature.code, "from": before, "to": value}, actor)
    entitlements.invalidate_all()


def remove_plan_feature(plan, feature, actor=None):
    deleted, _ = PlanFeature.objects.filter(plan=plan, feature=feature).delete()
    if deleted:
        _log("plan", plan, "feature_removed", {"feature": feature.code}, actor)
        entitlements.invalidate_all()


def log_change(object_type, obj, action, changes, actor=None):
    _log(object_type, obj, action, changes, actor)
    entitlements.invalidate_all()


def subscribers_on_plan(plan):
    return Subscription.objects.filter(plan=plan).exclude(
        status__in=(Subscription.Status.EXPIRED, Subscription.Status.CANCELED),
    )
