"""Superadmin review of branch storage add-on requests (School -> Branch detail)."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect

from apps.uploads.models import StorageAddOn
from apps.uploads.services import quota

from .auth import platform_admin_required


@platform_admin_required
def storage_addon_review(request, school_pk, branch_pk, pk):
    addon = get_object_or_404(StorageAddOn, pk=pk, branch_id=branch_pk, branch__school_id=school_pk)
    if request.method == "POST":
        decision = request.POST.get("decision")
        if decision not in ("approve", "reject"):
            messages.error(request, "Choose approve or reject.")
        else:
            try:
                quota.review_addon(addon, decision == "approve", request.user, request.POST.get("review_note", ""))
            except quota.StorageActionError as error:
                messages.error(request, str(error))
            else:
                messages.success(request, f"Storage add-on {'approved' if decision == 'approve' else 'rejected'}.")
    return redirect("admin_web:branch_detail", school_pk, branch_pk)
