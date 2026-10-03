"""Admin-web views grouped by business domain.

The legacy implementation remains behind a compatibility module while each
domain gets a stable import surface. URLs continue importing from this module,
so endpoint names and behavior remain unchanged during the migration.
"""

from .auth import dashboard, login_view, logout_view, platform_admin_required
from .activities import activity_delete, activity_detail, activity_form, activity_list
from .students import student_delete, student_detail, student_form, student_list
from .guardians import guardian_delete, guardian_detail, guardian_form, guardian_list
from .payments import (
    payment_delete, payment_detail, payment_form, payment_list, payment_review,
    student_invoice_detail, student_invoice_list,
)
from .settings import (
    role_permissions, settings_delete, settings_detail, settings_form, settings_list,
)
from .schools import (
    class_delete, class_detail, class_form,
    school_detail, school_form, school_list, school_set_active,
)
from .users import (
    location_children, user_activate, user_create, user_deactivate, user_detail,
    user_edit, user_list,
)
from .staff import staff_detail, staff_list
from .staff_mutations import staff_activate, staff_create, staff_deactivate, staff_edit
from .branches import branch_detail, branch_create, branch_edit, branch_deactivate, branch_set_active

__all__ = [name for name in globals() if not name.startswith("_")]
