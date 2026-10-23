"""Hard limits on account management, independent of module permissions."""
from rest_framework.exceptions import PermissionDenied


MANAGED_ROLES = {
    "ADMIN": {"ADMIN", "STAFF", "TEACHER", "PARENT"},
    "STAFF": {"STAFF", "TEACHER", "PARENT"},
    "TEACHER": {"PARENT"},
    "PARENT": set(),
}


def check_account_management(actor, target=None, new_role=None):
    allowed = MANAGED_ROLES.get(str(actor.role).upper(), set())
    if target is not None:
        # Django's privileged flags must never be bypassed via an ordinary role.
        if str(actor.role).upper() != "ADMIN" and (
            target.is_superuser or target.is_staff
        ):
            raise PermissionDenied("Only ADMIN can manage privileged accounts.")
        if str(target.role).upper() not in allowed:
            raise PermissionDenied("You cannot manage this user's role.")
    if new_role is not None and str(new_role).upper() not in allowed:
        raise PermissionDenied("You cannot assign this role.")
