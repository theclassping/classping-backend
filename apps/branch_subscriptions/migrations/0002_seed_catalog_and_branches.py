"""
Catalog (features, Starter / Growth / Pro, storage add-on) and a subscription
for every existing branch.

Existing branches start like a new branch: a trial on Starter limits
(DEFAULT_TRIAL_DAYS), with no email (open question: confirm with product).
What they have today is kept with overrides:
- a custom storage capacity (+ approved storage add-on requests) -> storage_bytes override
- payment gateway switched off today -> payment_gateway = false override
Running it again changes nothing.
"""
from datetime import timedelta

from django.conf import settings
from django.db import migrations
from django.db.models import Sum
from django.utils import timezone


def forwards(apps, schema_editor):
    from plan_subscriptions.catalog import load_catalog

    from apps.branch_subscriptions.catalog import CATALOG

    load_catalog(CATALOG, models=lambda name: apps.get_model("plan_subscriptions", name))

    Branch = apps.get_model("schools", "Branch")
    Plan = apps.get_model("plan_subscriptions", "Plan")
    Feature = apps.get_model("plan_subscriptions", "Feature")
    Subscription = apps.get_model("plan_subscriptions", "Subscription")
    SubscriptionEvent = apps.get_model("plan_subscriptions", "SubscriptionEvent")
    FeatureOverride = apps.get_model("plan_subscriptions", "FeatureOverride")
    StorageAddOn = apps.get_model("uploads", "StorageAddOn")

    config = getattr(settings, "PLAN_SUBSCRIPTIONS", {})
    plan = Plan.objects.get(code=config.get("TRIAL_PLAN", "starter"))
    price = plan.prices.filter(is_active=True).order_by("-created_at", "-pk").first()
    days = plan.trial_days if plan.trial_days is not None else int(config.get("DEFAULT_TRIAL_DAYS", 180))
    storage = Feature.objects.get(code="storage_bytes")
    gateway = Feature.objects.get(code="payment_gateway")
    now = timezone.now()

    for branch in Branch.objects.all():
        if Subscription.objects.filter(subscriber_id=branch.pk).exists():
            continue
        sub = Subscription.objects.create(
            subscriber_id=branch.pk, plan=plan, price=price, status="trialing",
            trial_start=now, trial_end=now + timedelta(days=days),
            metadata={"created_by": "migration:existing_branch"},
        )
        SubscriptionEvent.objects.create(
            subscription=sub, type="trial_started", data={"plan": plan.code, "days": days, "existing_branch": True},
        )
        addon_bytes = StorageAddOn.objects.filter(branch_id=branch.pk, status="approved").aggregate(
            total=Sum("size_bytes"),
        )["total"] or 0
        if branch.storage_capacity_bytes is not None or addon_bytes:
            base = branch.storage_capacity_bytes
            if base is None:
                base = settings.DEFAULT_BRANCH_STORAGE_BYTES
            FeatureOverride.objects.get_or_create(
                subscriber_id=branch.pk, feature=storage,
                defaults={"value": base + addon_bytes, "reason": "Capacity before subscriptions (incl. approved add-ons)"},
            )
        if not branch.is_payment_gateway_enabled:
            FeatureOverride.objects.get_or_create(
                subscriber_id=branch.pk, feature=gateway,
                defaults={"value": False, "reason": "Online payment was off before subscriptions"},
            )


class Migration(migrations.Migration):
    dependencies = [
        ("branch_subscriptions", "0001_initial"),
        ("plan_subscriptions", "0001_initial"),
        ("schools", "0007_merge_20261110_1105"),
        ("uploads", "0004_storage_addon"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
