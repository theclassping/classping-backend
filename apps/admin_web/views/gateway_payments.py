"""Admin web pages for payment gateway checkouts (Classping admins / ops)."""

from ..views_common import *
from apps.core.exceptions import CodedAPIException
from payment_aggregator.exceptions import PaymentAggregatorError
from apps.payment_aggregator import PaymentAggregator
from apps.payment_gateway import services as gateway_services
from apps.payment_gateway.models import GatewayPayment


@platform_admin_required
def gateway_payment_list(request):
    payments = GatewayPayment.objects.select_related("branch__school", "student").order_by("-created_at")
    status_filter = request.GET.get("status", "")
    branch_id = request.GET.get("branch", "")
    flag = request.GET.get("flag", "")
    settlement = request.GET.get("settlement", "")
    search = request.GET.get("q", "").strip()
    if status_filter in GatewayPayment.Status.values:
        payments = payments.filter(status=status_filter)
    if settlement == "settled":
        payments = payments.filter(settled_at__isnull=False)
    elif settlement == "pending":  # paid, money not settled by the provider yet
        payments = payments.filter(status=GatewayPayment.Status.PAID, settled_at__isnull=True)
    if branch_id:
        payments = payments.filter(branch_id=branch_id)
    if flag == "needs_refund":
        payments = payments.filter(needs_refund=True)
    elif flag == "needs_review":
        payments = payments.filter(needs_review=True)
    if search:
        payments = payments.filter(
            Q(payment_no__icontains=search)
            | Q(provider_trx_id__icontains=search)
            | Q(student__first_name__icontains=search)
            | Q(student__last_name__icontains=search)
        )
    return render(
        request,
        "admin_web/gateway_payments/list.html",
        {
            "page_obj": paginate_admin(payments, request),
            "statuses": GatewayPayment.Status.choices,
            "status_filter": status_filter,
            "branch_id": branch_id,
            "flag": flag,
            "settlement": settlement,
            "search": search,
            "branches": Branch.objects.select_related("school").order_by("school__name", "name"),
        },
    )


@platform_admin_required
def gateway_payment_detail(request, pk):
    gateway_payment = get_object_or_404(
        GatewayPayment.objects.select_related("branch__school", "student", "guardian", "cancelled_by"),
        pk=pk,
    )
    return render(
        request,
        "admin_web/gateway_payments/detail.html",
        {
            "gateway_payment": gateway_payment,
            "items": gateway_payment.items.select_related("student_invoice__fee_type"),
            "payments": gateway_payment.payments.select_related("student_invoice"),
            "ledger_entries": gateway_payment.ledger_entries.all(),
            "can_cancel": gateway_payment.status == GatewayPayment.Status.PENDING,
            "can_refund": _refund_offered(gateway_payment),
            "can_settle": gateway_payment.status == GatewayPayment.Status.PAID and not gateway_payment.settled_at,
        },
    )


def _refund_offered(gateway_payment):
    """Show the Refund button: flagged checkout, not refunded yet (or a
    PROCESSING refund to resend), provider with an online refund."""
    if gateway_payment.refund_status == GatewayPayment.RefundStatus.PROCESSING:
        pass
    elif not (
        gateway_payment.status == GatewayPayment.Status.PAID
        and gateway_payment.needs_refund
        and not gateway_payment.refund_status
    ):
        return False
    try:
        return PaymentAggregator.using(gateway_payment.provider).can_refund()
    except PaymentAggregatorError:
        return False


@platform_admin_required
def gateway_payment_refund(request, pk):
    if request.method == "POST":
        try:
            gateway_payment = gateway_services.refund_gateway_payment(request.user, pk, request.POST.get("reason", ""))
        except CodedAPIException as error:
            messages.error(request, error.message)
        else:
            if gateway_payment.refund_status == GatewayPayment.RefundStatus.REFUNDED:
                messages.success(request, "Refunded {} to the payer.".format(gateway_payment.refund_amount))
            else:
                messages.warning(
                    request, "Refund sent; the provider has not confirmed it yet. Press Refund again later to resend."
                )
    return redirect("admin_web:gateway_payment_detail", pk=pk)


@platform_admin_required
def gateway_payment_sync(request, pk):
    if request.method == "POST":
        try:
            gateway_payment = gateway_services.sync_gateway_payment(pk)
        except PaymentAggregatorError as error:
            messages.error(request, "Provider check failed: {}".format(error.provider_message or error))
        else:
            messages.success(request, "Status synced: {}.".format(gateway_payment.get_status_display()))
    return redirect("admin_web:gateway_payment_detail", pk=pk)


@platform_admin_required
def gateway_payment_settle(request, pk):
    if request.method == "POST":
        get_object_or_404(GatewayPayment, pk=pk)
        if gateway_services.settle_gateway_payment_manually(request.user, pk, request.POST.get("note", "")):
            messages.success(request, "Marked settled; the amount moved to the branch available balance.")
        else:
            messages.error(request, "Only a paid, unsettled online payment can be marked settled.")
    return redirect("admin_web:gateway_payment_detail", pk=pk)


@platform_admin_required
def gateway_payment_cancel(request, pk):
    if request.method == "POST":
        try:
            gateway_services.cancel_gateway_payment(request.user, pk, request.POST.get("reason", ""))
        except CodedAPIException as error:
            messages.error(request, error.message)
        else:
            messages.success(request, "Online payment cancelled; the invoices are open for manual payment.")
    return redirect("admin_web:gateway_payment_detail", pk=pk)
