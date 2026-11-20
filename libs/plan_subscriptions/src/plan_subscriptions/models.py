"""
Catalog (what is sold): Feature, Plan, PlanPrice, PlanFeature, AddOn, AddOnFeature.
Per subscriber: Subscription, SubscriptionAddOn, FeatureOverride, UsageRecord,
SubscriptionInvoice, SubscriptionEvent. Audit: CatalogChange.

State changes go through plan_subscriptions.services, not model saves.
"""
from django.conf import settings
from django.db import models

SUBSCRIBER_MODEL = getattr(settings, "PLAN_SUBSCRIPTIONS_SUBSCRIBER_MODEL")
MONEY = {"max_digits": 14, "decimal_places": 2}


class Feature(models.Model):
    class Kind(models.TextChoices):
        BOOLEAN = "boolean", "On / off"
        LIMIT = "limit", "Limit"
        METERED = "metered", "Metered"

    class OnExpiry(models.TextChoices):
        LOCK = "lock", "Read-only after expiry"
        KEEP = "keep", "Keep last value after expiry"

    class ResetPeriod(models.TextChoices):
        NONE = "none", "Never"
        MONTHLY = "monthly", "Monthly"

    # Used in host code: entitlements.has(subscriber, code). Fixed once created.
    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # Display unit; "bytes" is shown as GB in admin forms.
    unit = models.CharField(max_length=20, blank=True)
    reset_period = models.CharField(max_length=10, choices=ResetPeriod.choices, default=ResetPeriod.NONE)
    on_expiry = models.CharField(max_length=10, choices=OnExpiry.choices, default=OnExpiry.LOCK)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "subs_features"
        ordering = ["sort_order", "code"]

    def __str__(self):
        return self.name


class Plan(models.Model):
    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    # Null = PLAN_SUBSCRIPTIONS["DEFAULT_TRIAL_DAYS"].
    trial_days = models.PositiveIntegerField(null=True, blank=True)
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subs_plans"
        ordering = ["sort_order", "code"]

    def __str__(self):
        return self.name

    def current_price(self, interval="month"):
        return self.prices.filter(is_active=True, interval=interval).order_by("-created_at", "-pk").first()


class PlanPrice(models.Model):
    """Never edited in place: a new price is a new row, so subscribers keep theirs."""

    class Interval(models.TextChoices):
        MONTH = "month", "Month"
        YEAR = "year", "Year"

    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="prices")
    interval = models.CharField(max_length=10, choices=Interval.choices, default=Interval.MONTH)
    interval_count = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(**MONEY)  # excluding tax
    currency = models.CharField(max_length=3, default="IDR")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subs_plan_prices"
        ordering = ["plan", "-created_at", "-pk"]

    def __str__(self):
        return f"{self.plan.name} {self.currency} {self.amount:,.0f}/{self.interval}"


class PlanFeature(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="plan_features")
    feature = models.ForeignKey(Feature, on_delete=models.PROTECT, related_name="plan_values")
    # true / false for boolean; a number for limit and metered; null = unlimited.
    value = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "subs_plan_features"
        constraints = [models.UniqueConstraint(fields=["plan", "feature"], name="subs_plan_feature_unique")]

    def __str__(self):
        return f"{self.plan.code}.{self.feature.code}={self.value}"


class AddOn(models.Model):
    class Billing(models.TextChoices):
        RECURRING = "recurring", "Recurring (every period)"
        ONE_TIME = "one_time", "One-time"

    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    billing = models.CharField(max_length=10, choices=Billing.choices, default=Billing.RECURRING)
    price = models.DecimalField(**MONEY)  # per unit, excluding tax
    currency = models.CharField(max_length=3, default="IDR")
    # Total units one subscription may hold at once; null = no limit.
    max_quantity = models.PositiveIntegerField(null=True, blank=True)
    # Empty = can be bought on every plan.
    plans = models.ManyToManyField(Plan, blank=True, related_name="addons", db_table="subs_plan_addons")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subs_addons"
        ordering = ["sort_order", "code"]

    def __str__(self):
        return self.name

    def available_on(self, plan):
        plan_ids = [p.pk for p in self.plans.all()]
        return not plan_ids or plan.pk in plan_ids


class AddOnFeature(models.Model):
    class Mode(models.TextChoices):
        GRANT = "grant", "Switch on / set"
        INCREMENT = "increment", "Add value x quantity"

    addon = models.ForeignKey(AddOn, on_delete=models.CASCADE, related_name="addon_features")
    feature = models.ForeignKey(Feature, on_delete=models.PROTECT, related_name="addon_values")
    value = models.JSONField(null=True, blank=True)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.INCREMENT)

    class Meta:
        db_table = "subs_addon_features"
        constraints = [models.UniqueConstraint(fields=["addon", "feature"], name="subs_addon_feature_unique")]


class Subscription(models.Model):
    """One row per subscriber; renewed in place."""

    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        EXPIRED = "expired", "Expired"
        CANCELED = "canceled", "Canceled"

    subscriber = models.OneToOneField(SUBSCRIBER_MODEL, on_delete=models.CASCADE, related_name="plan_subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    price = models.ForeignKey(PlanPrice, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=10, choices=Status.choices, db_index=True)
    trial_start = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    # End of the last paid period. Access is covered until max(trial_end, paid_through).
    paid_through = models.DateTimeField(null=True, blank=True)
    # A price that takes over at pending_from (scheduled downgrade, tier picked for after the trial).
    pending_price = models.ForeignKey(
        PlanPrice, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
    )
    pending_from = models.DateTimeField(null=True, blank=True)
    # Set when it becomes past_due; read-only from this moment.
    grace_ends_at = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subs_subscriptions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subscriber} – {self.plan.name} ({self.status})"


class SubscriptionAddOn(models.Model):
    """One purchase of an add-on; several purchases of the same add-on add up."""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Waiting for payment"
        ACTIVE = "active", "Active"
        ENDING = "ending", "Ends at period end"
        ENDED = "ended", "Ended"
        VOID = "void", "Void"

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="addons")
    addon = models.ForeignKey(AddOn, on_delete=models.PROTECT, related_name="purchases")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(**MONEY)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subs_subscription_addons"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="subs_addon_purchase_idempotency",
            )
        ]

    def __str__(self):
        return f"{self.addon.name} x {self.quantity} ({self.status})"


class FeatureOverride(models.Model):
    """A custom value for one subscriber; replaces plan + add-ons for that feature."""

    subscriber = models.ForeignKey(SUBSCRIBER_MODEL, on_delete=models.CASCADE, related_name="feature_overrides")
    feature = models.ForeignKey(Feature, on_delete=models.PROTECT, related_name="overrides")
    value = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subs_feature_overrides"
        constraints = [models.UniqueConstraint(fields=["subscriber", "feature"], name="subs_override_unique")]


class UsageRecord(models.Model):
    subscriber = models.ForeignKey(SUBSCRIBER_MODEL, on_delete=models.CASCADE, related_name="usage_records")
    feature = models.ForeignKey(Feature, on_delete=models.PROTECT, related_name="usage_records")
    quantity = models.IntegerField()
    period_start = models.DateField()
    idempotency_key = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subs_usage_records"
        indexes = [models.Index(fields=["subscriber", "feature", "period_start"], name="subs_usage_lookup")]


class SubscriptionInvoice(models.Model):
    class Kind(models.TextChoices):
        FIRST = "first", "First period"
        RENEWAL = "renewal", "Renewal"
        UPGRADE = "upgrade", "Upgrade (prorated)"
        ADDON = "addon", "Add-on"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    class Start(models.TextChoices):
        PERIOD = "period", "At period start"
        NOW = "now", "On payment"

    number = models.CharField(max_length=40, unique=True)
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="invoices")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # The plan price this invoice pays for (first / renewal / upgrade).
    price = models.ForeignKey(PlanPrice, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # The add-on purchase this invoice pays for (kind addon).
    addon_purchase = models.ForeignKey(
        SubscriptionAddOn, null=True, blank=True, on_delete=models.PROTECT, related_name="invoices",
    )
    # "now": the period starts when paid (start now during trial, after expiry).
    start = models.CharField(max_length=10, choices=Start.choices, default=Start.PERIOD)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    # [{"description", "quantity", "unit_price", "amount", "type", "ref"}], amounts as strings.
    lines = models.JSONField(default=list)
    subtotal = models.DecimalField(**MONEY)
    tax = models.DecimalField(**MONEY, default=0)
    total = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3, default="IDR")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    due_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    # Host payment reference (e.g. SUB-20261212-000031) or "manual: ...".
    paid_ref = models.CharField(max_length=100, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subs_invoices"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.number


class SubscriptionEvent(models.Model):
    """History of a subscription; dedupe_key stops a reminder being sent twice."""

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=40)
    dedupe_key = models.CharField(max_length=150, unique=True, null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subs_events"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.type} @ {self.created_at:%Y-%m-%d %H:%M}"


class CatalogChange(models.Model):
    """Who changed which plan, price, feature or add-on."""

    object_type = models.CharField(max_length=30)
    object_id = models.PositiveBigIntegerField()
    action = models.CharField(max_length=30)
    changes = models.JSONField(default=dict)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subs_catalog_changes"
        ordering = ["-created_at", "-pk"]
