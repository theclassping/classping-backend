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

    # School pages
    path(
        "schools/",
        views.school_list,
        name="school_list",
    ),

    path(
        "schools/add/",
        views.school_create,
        name="school_create",
    ),

    path(
        "schools/<int:pk>/",
        views.school_detail,
        name="school_detail",
    ),
    
    path(
        "schools/<int:pk>/edit/",
        views.school_edit,
        name="school_edit",
    ),
    
    # Branches
    path(
        "schools/<int:school_pk>/branches/add/",
        views.branch_create,
        name="branch_create",
    ),
    path(
        "schools/<int:school_pk>/branches/<int:pk>/edit/",
        views.branch_edit,
        name="branch_edit",
    ),

    path(
        "schools/<int:school_pk>/branches/<int:pk>/deactivate/",
        views.branch_deactivate,
        name="branch_deactivate",
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