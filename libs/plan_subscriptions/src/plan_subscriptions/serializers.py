from rest_framework import serializers

from . import conf
from .models import AddOn, Plan, SubscriptionAddOn, SubscriptionInvoice
from .status import access_until, effective_price, effective_status


def _features(plan):
    return {pf.feature.code: pf.value for pf in plan.plan_features.select_related("feature")}


class PlanSerializer(serializers.ModelSerializer):
    price_id = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    interval = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = ["id", "code", "name", "description", "price_id", "amount", "interval", "features"]

    def _price(self, plan):
        return plan.current_price()

    def get_price_id(self, plan):
        price = self._price(plan)
        return price.pk if price else None

    def get_amount(self, plan):
        price = self._price(plan)
        return str(price.amount) if price else None

    def get_interval(self, plan):
        price = self._price(plan)
        return price.interval if price else None

    def get_features(self, plan):
        return _features(plan)


class AddOnSerializer(serializers.ModelSerializer):
    features = serializers.SerializerMethodField()

    class Meta:
        model = AddOn
        fields = ["id", "code", "name", "description", "billing", "price", "max_quantity", "features"]

    def get_features(self, addon):
        return [
            {"feature": af.feature.code, "value": af.value, "mode": af.mode}
            for af in addon.addon_features.select_related("feature")
        ]


class PurchaseSerializer(serializers.ModelSerializer):
    addon_code = serializers.CharField(source="addon.code")
    addon_name = serializers.CharField(source="addon.name")

    class Meta:
        model = SubscriptionAddOn
        fields = ["id", "addon_code", "addon_name", "quantity", "unit_price", "status", "started_at", "ends_at"]


class InvoiceSerializer(serializers.ModelSerializer):
    plan_code = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionInvoice
        fields = [
            "id", "number", "kind", "start", "plan_code", "period_start", "period_end", "lines",
            "subtotal", "tax", "total", "currency", "status", "due_at", "paid_at",
        ]

    def get_plan_code(self, invoice):
        return invoice.price.plan.code if invoice.price_id else None


def subscription_payload(sub, entitlement_summary, now, usage=None):
    status = effective_status(sub, now)
    price = effective_price(sub, now)
    open_invoices = sub.invoices.filter(status=SubscriptionInvoice.Status.OPEN).select_related("price__plan")
    payload = {
        "id": sub.pk,
        "status": status,
        "plan": {"code": price.plan.code, "name": price.plan.name, "price_id": price.pk, "amount": str(price.amount)},
        "pending_plan": (
            {"code": sub.pending_price.plan.code, "name": sub.pending_price.plan.name, "from": sub.pending_from}
            if sub.pending_price_id and (sub.pending_from is None or sub.pending_from > now) else None
        ),
        "trial_start": sub.trial_start,
        "trial_end": sub.trial_end,
        "current_period_start": sub.current_period_start,
        "current_period_end": sub.current_period_end,
        "access_until": access_until(sub),
        "grace_ends_at": sub.grace_ends_at,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "currency": conf.get("CURRENCY"),
        "features": entitlement_summary["features"],
        "addons": PurchaseSerializer(
            sub.addons.exclude(status__in=(SubscriptionAddOn.Status.VOID, SubscriptionAddOn.Status.ENDED))
            .select_related("addon"), many=True,
        ).data,
        "open_invoices": InvoiceSerializer(open_invoices, many=True).data,
    }
    if usage:
        payload["usage"] = usage
    return payload
