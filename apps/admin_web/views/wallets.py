"""Admin web pages for branch wallets and withdrawals (Classping admins / ops)."""

from ..forms import BalanceAdjustmentForm, WithdrawalResolveForm
from ..views_common import *
from apps.core.exceptions import CodedAPIException
from apps.payment_aggregator.exceptions import PaymentAggregatorError
from apps.wallets import services as wallet_services
from apps.wallets.models import BranchWallet, LedgerEntry, Withdrawal


@platform_admin_required
def wallet_list(request):
    wallets = BranchWallet.objects.select_related("branch__school").order_by("branch__school__name", "branch__name")
    search = request.GET.get("q", "").strip()
    if search:
        wallets = wallets.filter(Q(branch__name__icontains=search) | Q(branch__school__name__icontains=search))
    return render(
        request,
        "admin_web/wallets/list.html",
        {
            "page_obj": paginate_admin(wallets, request),
            "search": search,
            "platform": wallet_services.get_platform_balance(),
        },
    )


@platform_admin_required
def wallet_detail(request, branch_pk):
    branch = get_object_or_404(Branch.objects.select_related("school"), pk=branch_pk)
    form = BalanceAdjustmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            wallet_services.adjust_balance(
                request.user, branch.pk, form.cleaned_data["amount"], form.cleaned_data["note"]
            )
        except CodedAPIException as error:
            form.add_error("amount", error.message)
        else:
            messages.success(request, "Balance corrected.")
            return redirect("admin_web:wallet_detail", branch_pk=branch.pk)

    entries = LedgerEntry.objects.filter(branch=branch).select_related(
        "gateway_payment", "withdrawal", "created_by"
    ).order_by("-created_at", "-pk")
    entry_type = request.GET.get("entry_type", "")
    if entry_type in LedgerEntry.EntryType.values:
        entries = entries.filter(entry_type=entry_type)
    return render(
        request,
        "admin_web/wallets/detail.html",
        {
            "branch": branch,
            "wallet": BranchWallet.objects.filter(branch=branch).first(),
            "page_obj": paginate_admin(entries, request),
            "entry_types": LedgerEntry.EntryType.choices,
            "entry_type": entry_type,
            "form": form,
        },
    )


@platform_admin_required
def withdrawal_list(request):
    withdrawals = Withdrawal.objects.select_related("branch__school").order_by("-created_at")
    status_filter = request.GET.get("status", "")
    branch_id = request.GET.get("branch", "")
    flag = request.GET.get("flag", "")
    search = request.GET.get("q", "").strip()
    if status_filter in Withdrawal.Status.values:
        withdrawals = withdrawals.filter(status=status_filter)
    if branch_id:
        withdrawals = withdrawals.filter(branch_id=branch_id)
    if flag == "needs_review":
        withdrawals = withdrawals.filter(needs_review=True)
    elif flag == "stuck":
        withdrawals = withdrawals.filter(status=Withdrawal.Status.PROCESSING, provider_disbursement_id="")
    if search:
        withdrawals = withdrawals.filter(
            Q(withdrawal_no__icontains=search)
            | Q(provider_disbursement_id__icontains=search)
            | Q(account_holder_name__icontains=search)
        )
    return render(
        request,
        "admin_web/withdrawals/list.html",
        {
            "page_obj": paginate_admin(withdrawals, request),
            "statuses": Withdrawal.Status.choices,
            "status_filter": status_filter,
            "branch_id": branch_id,
            "flag": flag,
            "search": search,
            "branches": Branch.objects.select_related("school").order_by("school__name", "name"),
        },
    )


@platform_admin_required
def withdrawal_detail(request, pk):
    withdrawal = get_object_or_404(
        Withdrawal.objects.select_related("branch__school", "requested_by", "payout_account"), pk=pk
    )
    return render(
        request,
        "admin_web/withdrawals/detail.html",
        {
            "withdrawal": withdrawal,
            "ledger_entries": withdrawal.ledger_entries.order_by("pk"),
            "is_stuck": withdrawal.status == Withdrawal.Status.PROCESSING and not withdrawal.provider_disbursement_id,
            "resolve_form": WithdrawalResolveForm(),
        },
    )


@platform_admin_required
def withdrawal_sync(request, pk):
    if request.method == "POST":
        try:
            withdrawal = wallet_services.sync_withdrawal(pk)
        except PaymentAggregatorError as error:
            messages.error(request, "Provider check failed: {}".format(error.provider_message or error))
        else:
            messages.success(request, "Status synced: {}.".format(withdrawal.get_status_display()))
    return redirect("admin_web:withdrawal_detail", pk=pk)


@platform_admin_required
def withdrawal_resend(request, pk):
    if request.method == "POST":
        try:
            withdrawal = wallet_services.resend_withdrawal(pk)
        except CodedAPIException as error:
            messages.error(request, error.message)
        else:
            messages.success(request, "Resent. Status: {}.".format(withdrawal.get_status_display()))
    return redirect("admin_web:withdrawal_detail", pk=pk)


@platform_admin_required
def withdrawal_resolve(request, pk, succeeded):
    form = WithdrawalResolveForm(request.POST or None)
    if request.method == "POST":
        if not form.is_valid():
            messages.error(request, "A note is required.")
        else:
            try:
                withdrawal = wallet_services.resolve_withdrawal(
                    request.user, pk, succeeded, form.cleaned_data["note"]
                )
            except CodedAPIException as error:
                messages.error(request, error.message)
            else:
                messages.success(request, "Withdrawal marked {}.".format(withdrawal.get_status_display()))
    return redirect("admin_web:withdrawal_detail", pk=pk)
