from ..views_common import *

@login_required(login_url="admin_web:login")
def user_detail(request, pk):
    user = get_object_or_404(User.objects.select_related("staff__branch", "guardian"), pk=pk)
    return render(request, "admin_web/users/detail.html", {"user_obj": user})


@login_required(login_url="admin_web:login")
def user_list(request):
    """
    Display all users.

    Users can be:
        - Admin
        - Staff
        - Teacher
        - Parent

    We order newest users first.
    """

    search = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    active = request.GET.get("active", "")
    users = (
        User.objects
        .all()
        .order_by("-created_at")
    )
    if search:
        users = users.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
        )
    if role in dict(User.Role.choices):
        users = users.filter(role=role)
    if active in ("true", "false"):
        users = users.filter(is_active=active == "true")

    return render(
        request,
        "admin_web/users/list.html",
        {
            "users": users, "search": search, "role": role, "active": active,
            "roles": User.Role.choices,
        },
    )


@login_required(login_url="admin_web:login")
def user_create(request):
    """
    Create a new User account.

    The password is stored using Django's password hashing
    through user.set_password().
    """

    if request.method == "POST":

        email = request.POST.get(
            "email",
            "",
        ).strip().lower()

        first_name = request.POST.get(
            "first_name",
            "",
        ).strip()

        last_name = request.POST.get(
            "last_name",
            "",
        ).strip()

        role = request.POST.get(
            "role",
            "",
        ).strip()

        password = request.POST.get(
            "password",
            "",
        )

        confirm_password = request.POST.get(
            "confirm_password",
            "",
        )

        is_active = (
            request.POST.get("is_active") == "on"
        )

        errors = []

        # -----------------------------------------------------
        # Validation
        # -----------------------------------------------------

        if not email:
            errors.append(
                "Email is required."
            )

        if not first_name:
            errors.append(
                "First name is required."
            )

        if not role:
            errors.append(
                "Role is required."
            )

        if role not in User.Role.values:
            errors.append(
                "Invalid user role."
            )

        if not password:
            errors.append(
                "Password is required."
            )

        if password != confirm_password:
            errors.append(
                "Passwords do not match."
            )

        if (
            email
            and User.objects.filter(
                email=email,
            ).exists()
        ):
            errors.append(
                "A user with this email already exists."
            )

        # -----------------------------------------------------
        # Validation failed
        # -----------------------------------------------------

        if errors:

            return render(
                request,
                "admin_web/users/form.html",
                {
                    "errors": errors,

                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "role": role,
                    "is_active": is_active,

                    "roles": User.Role.choices,

                    "is_edit": False,
                },
            )

        # -----------------------------------------------------
        # Create User
        # -----------------------------------------------------

        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_active=is_active,
        )

        # IMPORTANT:
        # Never save the raw password directly.
        #
        # set_password() hashes the password.
        user.set_password(password)

        user.save()

        # -----------------------------------------------------
        # Success
        # -----------------------------------------------------

        messages.success(
            request,
            f'User "{user.full_name}" was created successfully.',
        )

        return redirect(
            "admin_web:user_list",
        )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    return render(
        request,
        "admin_web/users/form.html",
        {
            "roles": User.Role.choices,
            "is_active": True,
            "is_edit": False,
        },
    )


@login_required(login_url="admin_web:login")
def user_edit(request, pk):
    """
    Edit an existing User.

    Password is optional when editing.

    If the password fields are empty, the existing password
    remains unchanged.
    """

    user = get_object_or_404(
        User,
        pk=pk,
    )

    if request.method == "POST":

        email = request.POST.get(
            "email",
            "",
        ).strip().lower()

        first_name = request.POST.get(
            "first_name",
            "",
        ).strip()

        last_name = request.POST.get(
            "last_name",
            "",
        ).strip()

        role = request.POST.get(
            "role",
            "",
        ).strip()

        password = request.POST.get(
            "password",
            "",
        )

        confirm_password = request.POST.get(
            "confirm_password",
            "",
        )

        is_active = (
            request.POST.get("is_active") == "on"
        )

        errors = []

        # -----------------------------------------------------
        # Validation
        # -----------------------------------------------------

        if not email:
            errors.append(
                "Email is required."
            )

        if not first_name:
            errors.append(
                "First name is required."
            )

        if role not in User.Role.values:
            errors.append(
                "Invalid user role."
            )

        if (
            email
            and User.objects.filter(
                email=email,
            )
            .exclude(pk=user.pk)
            .exists()
        ):
            errors.append(
                "A user with this email already exists."
            )

        # -----------------------------------------------------
        # Password validation
        #
        # Password is optional during edit.
        # -----------------------------------------------------

        if password or confirm_password:

            if password != confirm_password:

                errors.append(
                    "Passwords do not match."
                )

        # -----------------------------------------------------
        # Validation failed
        # -----------------------------------------------------

        if errors:

            return render(
                request,
                "admin_web/users/form.html",
                {
                    "user": user,

                    "errors": errors,

                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "role": role,
                    "is_active": is_active,

                    "roles": User.Role.choices,

                    "is_edit": True,
                },
            )

        # -----------------------------------------------------
        # Update User
        # -----------------------------------------------------

        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.role = role
        user.is_active = is_active

        # -----------------------------------------------------
        # Update password only if provided
        # -----------------------------------------------------

        if password:
            user.set_password(password)

        user.save()

        # -----------------------------------------------------
        # Success
        # -----------------------------------------------------

        messages.success(
            request,
            f'User "{user.full_name}" was updated successfully.',
        )

        return redirect(
            "admin_web:user_list",
        )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    return render(
        request,
        "admin_web/users/form.html",
        {
            "user": user,

            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "is_active": user.is_active,

            "roles": User.Role.choices,

            "is_edit": True,
        },
    )


@login_required(login_url="admin_web:login")
def user_deactivate(request, pk):
    """
    Deactivate a User.

    The user is not deleted.
    """

    user = get_object_or_404(
        User,
        pk=pk,
    )

    if request.method == "POST":

        user.is_active = False

        user.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

        messages.success(
            request,
            f'User "{user.full_name}" was deactivated successfully.',
        )

    return redirect(
        "admin_web:user_list",
    )


@login_required(login_url="admin_web:login")
def user_activate(request, pk):
    """
    Activate a previously deactivated User.
    """

    user = get_object_or_404(
        User,
        pk=pk,
    )

    if request.method == "POST":

        user.is_active = True

        user.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

        messages.success(
            request,
            f'User "{user.full_name}" was activated successfully.',
        )

    return redirect(
        "admin_web:user_list",
    )


@login_required(login_url="admin_web:login")
def location_children(request):
    """
    Return the direct children of a Location.

    This endpoint is used only by the Django Admin Web
    dependent location dropdowns.

    Example:

        GET /admin-web/locations/children/?parent_id=2

    Response:

        {
            "results": [
                {
                    "id": 3,
                    "name": "Kota Bandung"
                }
            ]
        }

    We use Django session authentication here because the
    Admin Web user is already logged in with Django login().
    """

    # ---------------------------------------------------------
    # Get parent_id from the query string
    # ---------------------------------------------------------

    parent_id = request.GET.get("parent_id", "").strip()

    if not parent_id:
        return JsonResponse(
            {
                "results": [],
                "error": "parent_id is required.",
            },
            status=400,
        )

    # ---------------------------------------------------------
    # Find children
    # ---------------------------------------------------------
    #
    # Example:
    #
    # parent_id = 2
    #
    # returns:
    #
    # Kota Bandung
    # Bekasi
    # Bogor
    # etc.
    #
    locations = (
        Location.objects
        .filter(parent_id=parent_id)
        .order_by("name")
    )

    # ---------------------------------------------------------
    # Convert queryset to JSON-friendly data
    # ---------------------------------------------------------

    results = [
        {
            "id": location.id,
            "name": location.name,
        }
        for location in locations
    ]

    return JsonResponse(
        {
            "results": results,
        }
    )

