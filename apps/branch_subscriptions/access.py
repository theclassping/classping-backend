"""Who is the subscriber of a request, and who may manage the subscription."""
from rest_framework.permissions import BasePermission

from apps.schools.models import Branch


def _is_platform_admin(user):
    return bool(user.is_superuser or str(getattr(user, "role", "")).upper() == "ADMIN")


def staff_branch(user):
    """Every staff type (principal, teacher, officer) of an active staff profile."""
    staff = getattr(user, "staff", None)
    if staff is None or not staff.is_active or staff.branch_id is None:
        return None
    return staff.branch


def branch_from_request(request):
    user = request.user
    if not user or not user.is_authenticated:
        return None
    branch = staff_branch(user)
    if branch is not None:
        return branch
    if _is_platform_admin(user):
        # Platform admins act for a branch named in the request.
        branch_id = request.query_params.get("branch_id") or getattr(request, "data", {}).get("branch_id")
        if branch_id and str(branch_id).isdigit():
            return Branch.objects.filter(pk=branch_id).first()
    return None


def branch_label(branch):
    """Shown in admin and emails: "SD Harapan Bangsa – Main Campus"."""
    school = getattr(branch, "school", None)
    return f"{school.name} – {branch.name}" if school else branch.name


class IsBranchStaff(BasePermission):
    """Any active staff of a branch (they can remind each other), or a platform admin."""

    message = "Only branch staff can manage the subscription."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return staff_branch(user) is not None or _is_platform_admin(user)
