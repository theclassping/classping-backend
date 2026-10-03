from django.urls import path

from . import views


app_name = "admin_web"


urlpatterns = [
    # Login page
    path(
        "login/",
        views.login_view,
        name="login",
    ),

    # Logout
    path(
        "logout/",
        views.logout_view,
        name="logout",
    ),

    # Admin dashboard/home
    path(
        "",
        views.dashboard,
        name="dashboard",
    ),

    path("activities/", views.activity_list, name="activity_list"),
    path("activities/add/", views.activity_form, name="activity_create"),
    path("activities/<int:pk>/", views.activity_detail, name="activity_detail"),
    path("activities/<int:pk>/edit/", views.activity_form, name="activity_edit"),
    path("activities/<int:pk>/delete/", views.activity_delete, name="activity_delete"),
    path("students/", views.student_list, name="student_list"),
    path("students/add/", views.student_form, name="student_create"),
    path("students/<int:pk>/", views.student_detail, name="student_detail"),
    path("students/<int:pk>/edit/", views.student_form, name="student_edit"),
    path("students/<int:pk>/delete/", views.student_delete, name="student_delete"),
    path("guardians/", views.guardian_list, name="guardian_list"),
    path("guardians/add/", views.guardian_form, name="guardian_create"),
    path("guardians/<int:pk>/", views.guardian_detail, name="guardian_detail"),
    path("guardians/<int:pk>/edit/", views.guardian_form, name="guardian_edit"),
    path("guardians/<int:pk>/delete/", views.guardian_delete, name="guardian_delete"),
    path("classes/<int:pk>/", views.class_detail, name="class_detail"),
    path("schools/<int:school_pk>/classes/add/", views.class_form, name="class_create"),
    path("schools/<int:school_pk>/classes/<int:pk>/edit/", views.class_form, name="class_edit"),
    path("schools/<int:school_pk>/classes/<int:pk>/delete/", views.class_delete, name="class_delete"),
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/add/", views.payment_form, name="payment_create"),
    path("payments/<int:pk>/", views.payment_detail, name="payment_detail"),
    path("payments/<int:pk>/edit/", views.payment_form, name="payment_edit"),
    path("payments/<int:pk>/delete/", views.payment_delete, name="payment_delete"),
    path(
        "payments/<int:pk>/<str:action>/",
        views.payment_review,
        name="payment_review",
    ),
    path("student-invoices/", views.student_invoice_list, name="student_invoice_list"),
    path("student-invoices/<int:pk>/", views.student_invoice_detail, name="student_invoice_detail"),
    path("settings/<slug:section>/", views.settings_list, name="settings_list"),
    path("settings/<slug:section>/add/", views.settings_form, name="settings_create"),
    path(
        "settings/<slug:section>/<int:pk>/",
        views.settings_detail,
        name="settings_detail",
    ),
    path(
        "settings/<slug:section>/<int:pk>/edit/",
        views.settings_form,
        name="settings_edit",
    ),
    path(
        "settings/<slug:section>/<int:pk>/delete/",
        views.settings_delete,
        name="settings_delete",
    ),

    # School pages
    path(
        "schools/",
        views.school_list,
        name="school_list",
    ),

    path(
        "schools/add/",
        views.school_form,
        name="school_create",
    ),

    path(
        "schools/<int:pk>/",
        views.school_detail,
        name="school_detail",
    ),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("staff/<int:pk>/", views.staff_detail, name="staff_detail"),
    
    path(
        "schools/<int:pk>/edit/",
        views.school_form,
        name="school_edit",
    ),
    path("schools/<int:pk>/deactivate/", views.school_set_active, {"active": False}, name="school_deactivate"),
    path("schools/<int:pk>/activate/", views.school_set_active, {"active": True}, name="school_activate"),
    
    # Branches
    path(
        "schools/<int:school_pk>/branches/add/",
        views.branch_create,
        name="branch_create",
    ),
    path(
        "schools/<int:school_pk>/branches/<int:pk>/",
        views.branch_detail,
        name="branch_detail",
    ),
    path(
        "schools/<int:school_pk>/branches/<int:pk>/edit/",
        views.branch_edit,
        name="branch_edit",
    ),

    path(
        "schools/<int:school_pk>/branches/<int:pk>/deactivate/",
        views.branch_set_active,
        name="branch_deactivate",
        kwargs={"active": False},
    ),
    path(
        "schools/<int:school_pk>/branches/<int:pk>/activate/",
        views.branch_set_active,
        name="branch_activate",
        kwargs={"active": True},
    ),
    
    # ---------------------------------------------------------
    # Admin Web Location API
    # ---------------------------------------------------------
    path(
        "locations/children/",
        views.location_children,
        name="location_children",
    ),
    
    # =========================================================
# Users
# =========================================================

path(
    "users/",
    views.user_list,
    name="user_list",
),

    path(
        "role-permissions/",
        views.role_permissions,
        name="role_permissions",
    ),

path(
    "users/add/",
    views.user_create,
    name="user_create",
),

path(
    "users/<int:pk>/edit/",
    views.user_edit,
    name="user_edit",
),

path(
    "users/<int:pk>/deactivate/",
    views.user_deactivate,
    name="user_deactivate",
),

path(
    "users/<int:pk>/activate/",
    views.user_activate,
    name="user_activate",
),

# Staff
path(
    "staff/",
    views.staff_list,
    name="staff_list",
),
path(
    "staff/add/",
    views.staff_create,
    name="staff_create",
),
path(
    "staff/<int:pk>/edit/",
    views.staff_edit,
    name="staff_edit",
),
path(
    "staff/<int:pk>/deactivate/",
    views.staff_deactivate,
    name="staff_deactivate",
),
path(
    "staff/<int:pk>/activate/",
    views.staff_activate,
    name="staff_activate",
),
]
