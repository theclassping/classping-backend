from apps.users.permissions import RoleBasedAccessPermission

from .services import get_withdrawal_branch


class WithdrawalAccessPermission(RoleBasedAccessPermission):
    """Module grants, then branch principal / officer only (checked before
    the request body is validated, so others always get 403)."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        get_withdrawal_branch(request.user)  # raises WITHDRAWAL_ROLE_FORBIDDEN
        return True
