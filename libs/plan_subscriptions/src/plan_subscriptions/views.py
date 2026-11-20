"""
Subscriber-facing API. Include ``plan_subscriptions.urls`` under any prefix.

The host decides who the subscriber of a request is (SUBSCRIBER_RESOLVER)
and who may call these views (API_PERMISSION_CLASSES).
Errors: {"detail": "...", "code": "...", **extra}.
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.module_loading import import_string
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import conf, entitlements, services
from .exceptions import InvalidRequest, InvoiceNotPayable, SubscriptionError, SubscriptionNotFound
from .models import AddOn, Plan, PlanPrice, SubscriptionAddOn, SubscriptionInvoice
from .serializers import AddOnSerializer, InvoiceSerializer, PlanSerializer, PurchaseSerializer, subscription_payload


def _permission_classes():
    return [import_string(path) for path in conf.get("API_PERMISSION_CLASSES")]


class SubscriberView(APIView):
    def get_permissions(self):
        return [cls() for cls in _permission_classes()]

    def handle_exception(self, exc):
        if isinstance(exc, SubscriptionError):
            body = {"detail": exc.message, "code": exc.code}
            body.update({k: v for k, v in exc.extra.items() if not hasattr(v, "pk")})
            return Response(body, status=exc.status)
        return super().handle_exception(exc)

    def subscriber(self):
        resolver = conf.load("SUBSCRIBER_RESOLVER")
        subscriber = resolver(self.request) if resolver else None
        if subscriber is None:
            raise SubscriptionNotFound("No subscriber for this account.")
        return subscriber

    def subscription(self):
        return services.get_subscription(self.subscriber())

    def idempotency_key(self):
        return (self.request.headers.get("Idempotency-Key") or "").strip()[:100]

    def _int(self, name, required=True, default=None):
        value = self.request.data.get(name, self.request.query_params.get(name, default))
        if value in (None, ""):
            if required:
                raise InvalidRequest(f"{name} is required.")
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            raise InvalidRequest(f"{name} must be a whole number.")


def _usage(subscriber):
    provider = conf.load("USAGE_PROVIDER")
    return provider(subscriber) if provider else None


class SubscriptionView(SubscriberView):
    """GET: the current subscription, limits, usage, add-ons and open invoices."""

    def get(self, request):
        subscriber = self.subscriber()
        sub = services.get_subscription(subscriber)
        now = timezone.now()
        return Response(subscription_payload(sub, entitlements.summary(subscriber), now, _usage(subscriber)))


class PlanListView(SubscriberView):
    """GET: plans and add-ons that can be bought."""

    def get(self, request):
        plans = Plan.objects.filter(is_active=True, is_public=True).prefetch_related("plan_features__feature")
        addons = AddOn.objects.filter(is_active=True)
        return Response({
            "currency": conf.get("CURRENCY"),
            "tax_rate": str(conf.tax_rate()),
            "plans": PlanSerializer(plans, many=True).data,
            "addons": AddOnSerializer(addons, many=True).data,
        })


class SubscribeView(SubscriberView):
    """POST {price_id, start: "period" | "now"}: invoice for a plan (trial, past due, expired)."""

    def post(self, request):
        sub = self.subscription()
        price = get_object_or_404(PlanPrice.objects.select_related("plan"), pk=self._int("price_id"))
        start = request.data.get("start") or SubscriptionInvoice.Start.PERIOD
        if start not in SubscriptionInvoice.Start.values:
            raise InvalidRequest('start must be "period" or "now".')
        invoice = services.subscribe(sub, price, start=start, actor=request.user)
        return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)


class ChangePlanView(SubscriberView):
    """POST {price_id}: upgrade (returns the prorated invoice) or downgrade at period end (invoice null)."""

    def post(self, request):
        sub = self.subscription()
        price = get_object_or_404(PlanPrice.objects.select_related("plan"), pk=self._int("price_id"))
        invoice = services.change_plan(sub, price, actor=request.user)
        return Response({"invoice": InvoiceSerializer(invoice).data if invoice else None})


class CancelView(SubscriberView):
    def post(self, request):
        sub = services.cancel(self.subscription(), actor=request.user)
        return Response({"cancel_at_period_end": sub.cancel_at_period_end})


class AddonQuoteView(SubscriberView):
    """GET ?addon_code=&quantity=: price now (prorated) and the fee per channel."""

    def get(self, request):
        sub = self.subscription()
        addon = get_object_or_404(AddOn, code=request.query_params.get("addon_code", ""), is_active=True)
        quote = services.addon_quote(sub, addon, self._int("quantity", required=False, default=1))
        backend = conf.billing_backend()
        channels = backend.quote_amount(quote["total"]) if hasattr(backend, "quote_amount") else []
        return Response({
            "addon_code": addon.code,
            "quantity": quote["quantity"],
            "unit_price": str(quote["unit_price"]),
            "period_end": quote["period_end"],
            "subtotal": str(quote["subtotal"]),
            "tax": str(quote["tax"]),
            "total": str(quote["total"]),
            "channels": channels,
        })


class AddonListView(SubscriberView):
    """
    GET: add-on purchases.
    POST {addon_code, quantity, channel_code?} + Idempotency-Key: buy in one step.
    With channel_code the payment is started too and returned under "payment".
    """

    def get(self, request):
        sub = self.subscription()
        purchases = sub.addons.exclude(status=SubscriptionAddOn.Status.VOID).select_related("addon")
        return Response(PurchaseSerializer(purchases, many=True).data)

    def post(self, request):
        sub = self.subscription()
        addon = get_object_or_404(AddOn, code=request.data.get("addon_code", ""), is_active=True)
        quantity = self._int("quantity", required=False, default=1)
        key = self.idempotency_key()
        channel_code = request.data.get("channel_code") or ""
        purchase, invoice = services.buy_addon(sub, addon, quantity, actor=request.user, idempotency_key=key)
        body = {"addon": PurchaseSerializer(purchase).data, "invoice": InvoiceSerializer(invoice).data, "payment": None}
        if channel_code and invoice is not None and invoice.status == SubscriptionInvoice.Status.OPEN:
            body["payment"] = conf.billing_backend().start_payment(
                invoice, channel_code, request.user, f"{key}:pay" if key else "",
            )
        return Response(body, status=status.HTTP_201_CREATED)


class AddonDetailView(SubscriberView):
    def delete(self, request, pk):
        sub = self.subscription()
        purchase = get_object_or_404(SubscriptionAddOn, pk=pk, subscription=sub)
        purchase = services.remove_addon(purchase, actor=request.user)
        return Response(PurchaseSerializer(purchase).data)


class InvoiceListView(SubscriberView):
    def get(self, request):
        sub = self.subscription()
        invoices = sub.invoices.select_related("price__plan")
        return Response(InvoiceSerializer(invoices, many=True).data)


class InvoiceDetailView(SubscriberView):
    def get(self, request, pk):
        invoice = get_object_or_404(SubscriptionInvoice, pk=pk, subscription=self.subscription())
        body = InvoiceSerializer(invoice).data
        body["payments"] = conf.billing_backend().list_payments(invoice)
        return Response(body)


class InvoiceChannelsView(SubscriberView):
    def get(self, request, pk):
        invoice = get_object_or_404(SubscriptionInvoice, pk=pk, subscription=self.subscription())
        if invoice.status != SubscriptionInvoice.Status.OPEN:
            raise InvoiceNotPayable()
        return Response({"invoice_total": str(invoice.total), "channels": conf.billing_backend().quote(invoice)})


class InvoiceCheckoutView(SubscriberView):
    """POST {channel_code} + Idempotency-Key: start paying an invoice."""

    def post(self, request, pk):
        invoice = get_object_or_404(SubscriptionInvoice, pk=pk, subscription=self.subscription())
        if invoice.status != SubscriptionInvoice.Status.OPEN:
            raise InvoiceNotPayable()
        channel_code = request.data.get("channel_code") or ""
        if not channel_code:
            raise InvalidRequest("channel_code is required.")
        payment = conf.billing_backend().start_payment(invoice, channel_code, request.user, self.idempotency_key())
        return Response(payment, status=status.HTTP_201_CREATED)


class PaymentDetailView(SubscriberView):
    def get(self, request, pk):
        return Response(conf.billing_backend().get_payment(pk, self.subscriber()))


class PaymentCancelView(SubscriberView):
    def post(self, request, pk):
        return Response(conf.billing_backend().cancel_payment(pk, self.subscriber(), request.user))
