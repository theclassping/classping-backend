"""Payout accounts of a branch (School -> Branch detail): view, edit, delete.

Accounts are created by withdrawals; withdrawals keep a snapshot of the
destination, so editing or deleting an account never changes their history.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.wallets.models import PayoutAccount

from ..forms import PayoutAccountForm
from .auth import platform_admin_required


def _get_account(school_pk, branch_pk, pk):
    return get_object_or_404(
        PayoutAccount.objects.select_related("branch__school"),
        pk=pk,
        branch_id=branch_pk,
        branch__school_id=school_pk,
    )


@platform_admin_required
def payout_account_edit(request, school_pk, branch_pk, pk):
    account = _get_account(school_pk, branch_pk, pk)
    form = PayoutAccountForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Payout account updated.")
        return redirect("admin_web:branch_detail", school_pk, branch_pk)
    return render(
        request,
        "admin_web/payout_accounts/form.html",
        {"account": account, "branch": account.branch, "school": account.branch.school, "form": form},
    )


@platform_admin_required
def payout_account_delete(request, school_pk, branch_pk, pk):
    account = _get_account(school_pk, branch_pk, pk)
    if request.method == "POST":
        account.delete()
        messages.success(request, "Payout account deleted.")
    return redirect("admin_web:branch_detail", school_pk, branch_pk)
