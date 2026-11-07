"""
Read-only queries for gateway payments, used by other apps.

An invoice is locked while it has an active GatewayPaymentItem; items are
deactivated when the checkout expires or is cancelled.
"""

from django.db.models import Count, Prefetch

from .models import GatewayPayment, GatewayPaymentItem


def get_active_checkout_for_invoice(invoice_id):
    """The checkout that currently locks ``invoice_id``, or None."""
    item = (
        GatewayPaymentItem.objects.select_related("gateway_payment")
        .filter(student_invoice_id=invoice_id, is_active=True)
        .first()
    )
    return item.gateway_payment if item else None


def gateway_payment_queryset():
    """Checkouts for the API (B3/B4), with items and the invoice count."""
    items = GatewayPaymentItem.objects.select_related(
        "student_invoice__fee_type"
    ).order_by("pk")
    return (
        GatewayPayment.objects.select_related("student")
        .prefetch_related(Prefetch("items", queryset=items))
        .annotate(invoice_count=Count("items", distinct=True))
        .order_by("-created_at", "-pk")
    )


def locked_invoice_ids():
    """Ids of all invoices locked by an active checkout (for querysets)."""
    return GatewayPaymentItem.objects.filter(is_active=True).values_list(
        "student_invoice_id", flat=True
    )
