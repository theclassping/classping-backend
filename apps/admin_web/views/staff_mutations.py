from ..views_common import *

def staff_create(request):
    """
    Create a Staff and its associated User account.

    Staff fields:
        - branch
        - first_name
        - last_name
        - email
        - phone
        - staff_type
        - hire_date
        - qualification
        - is_active

    User fields:
        - email
        - first_name
        - last_name
        - role
        - password
        - is_active
    """

    branches = (
        Branch.objects
        .filter(is_active=True)
        .select_related("school")
        .order_by("school__name", "name")
    )

    errors = []

    if request.method == "POST":

        branch_id = request.POST.get("branch")
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        staff_type = request.POST.get("staff_type", "").strip()
        hire_date = request.POST.get("hire_date", "").strip()
        qualification = request.POST.get("qualification", "").strip()

        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")

        is_active = request.POST.get("is_active") == "on"

        # ---------------------------------------------------------
        # Basic validation
        # ---------------------------------------------------------

        if not branch_id:
            errors.append("Branch is required.")

        if not first_name:
            errors.append("First name is required.")

        if not email:
            errors.append("Email is required.")

        if not staff_type:
            errors.append("Staff type is required.")

        if not hire_date:
            errors.append("Hire date is required.")

        if not qualification:
            errors.append("Qualification is required.")

        if password and password != confirm_password:
            errors.append("Password and confirmation password do not match.")

        # ---------------------------------------------------------
        # Validate staff type
        # ---------------------------------------------------------

        valid_staff_types = {
            choice[0]
            for choice in Staff.StaffType.choices
        }

        if staff_type and staff_type not in valid_staff_types:
            errors.append("Invalid staff type.")

        # ---------------------------------------------------------
        # Validate branch
        # ---------------------------------------------------------

        branch = None

        if branch_id:
            try:
                branch = Branch.objects.get(
                    pk=branch_id,
                    is_active=True,
                )
            except Branch.DoesNotExist:
                errors.append("Selected branch does not exist.")

        # ---------------------------------------------------------
        # Validate hire date
        # ---------------------------------------------------------

        parsed_hire_date = None

        if hire_date:
            try:
                parsed_hire_date = datetime.strptime(
                    hire_date,
                    "%Y-%m-%d",
                ).date()
            except ValueError:
                errors.append("Invalid hire date.")

        # ---------------------------------------------------------
        # Check duplicate email
        # ---------------------------------------------------------

        if email:

            if Staff.objects.filter(email=email).exists():
                errors.append(
                    "A staff member with this email already exists."
                )

            if User.objects.filter(email=email).exists():
                errors.append(
                    "A user with this email already exists."
                )

        # ---------------------------------------------------------
        # Create Staff + User
        # ---------------------------------------------------------

        if not errors:

            # Teacher -> TEACHER
            # Principal -> STAFF
            # Officer -> STAFF
            #
            # We use STAFF for Principal for now because your
            # User.Role does not currently have PRINCIPAL.

            if staff_type == Staff.StaffType.TEACHER:
                user_role = User.Role.TEACHER
            else:
                user_role = User.Role.STAFF

            with transaction.atomic():

                # Create login account
                temporary_password = (
                    generate_temporary_password() if not password else None
                )
                user = User.objects.create_user(
                    email=email,
                    password=password,
                    temporary_password=temporary_password,
                    first_name=first_name,
                    last_name=last_name,
                    role=user_role,
                    is_active=is_active,
                )

                # Create staff
                Staff.objects.create(
                    branch=branch,
                    user=user,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=phone,
                    staff_type=staff_type,
                    hire_date=parsed_hire_date,
                    qualification=qualification,
                    is_active=is_active,
                )

            messages.success(
                request,
                f'Staff "{first_name} {last_name}" was created successfully.',
            )

            return redirect("admin_web:staff_list")

    return render(
        request,
        "admin_web/staff/form.html",
        {
            "branches": branches,
            "staff_types": Staff.StaffType.choices,
            "errors": errors,
            "is_edit": False,
        },
    )


def staff_edit(request, pk):
    """
    Edit Staff and its associated User account.

    Password is optional when editing.
    """

    staff = get_object_or_404(
        Staff.objects.select_related("user", "branch"),
        pk=pk,
    )

    branches = (
        Branch.objects
        .filter(is_active=True)
        .select_related("school")
        .order_by("school__name", "name")
    )

    errors = []

    if request.method == "POST":

        branch_id = request.POST.get("branch")
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        phone = request.POST.get("phone", "").strip()
        staff_type = request.POST.get("staff_type", "").strip()
        hire_date = request.POST.get("hire_date", "").strip()
        qualification = request.POST.get("qualification", "").strip()

        password = request.POST.get("password", "")
        confirm_password = request.POST.get("confirm_password", "")

        is_active = request.POST.get("is_active") == "on"

        # ---------------------------------------------------------
        # Basic validation
        # ---------------------------------------------------------

        if not branch_id:
            errors.append("Branch is required.")

        if not first_name:
            errors.append("First name is required.")

        if not email:
            errors.append("Email is required.")

        if not staff_type:
            errors.append("Staff type is required.")

        if not hire_date:
            errors.append("Hire date is required.")

        if not qualification:
            errors.append("Qualification is required.")

        # Password is optional during edit
        if password or confirm_password:
            if password != confirm_password:
                errors.append(
                    "Password and confirmation password do not match."
                )

        # ---------------------------------------------------------
        # Validate staff type
        # ---------------------------------------------------------

        valid_staff_types = {
            choice[0]
            for choice in Staff.StaffType.choices
        }

        if staff_type and staff_type not in valid_staff_types:
            errors.append("Invalid staff type.")

        # ---------------------------------------------------------
        # Validate branch
        # ---------------------------------------------------------

        branch = None

        if branch_id:
            try:
                branch = Branch.objects.get(
                    pk=branch_id,
                    is_active=True,
                )
            except Branch.DoesNotExist:
                errors.append("Selected branch does not exist.")

        # ---------------------------------------------------------
        # Validate date
        # ---------------------------------------------------------

        parsed_hire_date = None

        if hire_date:
            try:
                parsed_hire_date = datetime.strptime(
                    hire_date,
                    "%Y-%m-%d",
                ).date()
            except ValueError:
                errors.append("Invalid hire date.")

        # ---------------------------------------------------------
        # Check duplicate Staff email
        # ---------------------------------------------------------

        if email:

            if (
                Staff.objects
                .filter(email=email)
                .exclude(pk=staff.pk)
                .exists()
            ):
                errors.append(
                    "A staff member with this email already exists."
                )

            # -----------------------------------------------------
            # Check duplicate User email
            # -----------------------------------------------------

            user_queryset = User.objects.filter(email=email)

            if staff.user:
                user_queryset = user_queryset.exclude(
                    pk=staff.user.pk
                )

            if user_queryset.exists():
                errors.append(
                    "A user with this email already exists."
                )

        # ---------------------------------------------------------
        # Update Staff + User
        # ---------------------------------------------------------

        if not errors:

            if staff_type == Staff.StaffType.TEACHER:
                user_role = User.Role.TEACHER
            else:
                user_role = User.Role.STAFF

            with transaction.atomic():

                # ---------------------------------------------
                # Update Staff
                # ---------------------------------------------

                staff.branch = branch
                staff.first_name = first_name
                staff.last_name = last_name
                staff.email = email
                staff.phone = phone
                staff.staff_type = staff_type
                staff.hire_date = parsed_hire_date
                staff.qualification = qualification
                staff.is_active = is_active

                staff.save()

                # ---------------------------------------------
                # Update associated User
                # ---------------------------------------------

                if staff.user:

                    user = staff.user

                    user.email = email
                    user.first_name = first_name
                    user.last_name = last_name
                    user.role = user_role
                    user.is_active = is_active

                    # Only change password if entered.
                    if password:
                        user.set_password(password)

                    user.save()

                else:
                    # -------------------------------------------------
                    # Legacy Staff without a User account.
                    #
                    # Because Staff.user is nullable, this can happen
                    # with old records.
                    #
                    # Create the missing login account with a generated
                    # password when one was not entered.
                    # -------------------------------------------------

                    temporary_password = (
                        generate_temporary_password() if not password else None
                    )
                    user = User.objects.create_user(
                        email=email,
                        password=password,
                        temporary_password=temporary_password,
                        first_name=first_name,
                        last_name=last_name,
                        role=user_role,
                        is_active=is_active,
                    )

                    staff.user = user
                    staff.save(
                        update_fields=[
                            "user",
                            "updated_at",
                        ]
                    )

            messages.success(
                request,
                f'Staff "{first_name} {last_name}" was updated successfully.',
            )

            return redirect("admin_web:staff_list")

    return render(
        request,
        "admin_web/staff/form.html",
        {
            "staff": staff,
            "branches": branches,
            "staff_types": Staff.StaffType.choices,
            "errors": errors,
            "is_edit": True,
        },
    )


def staff_deactivate(request, pk):

    staff = get_object_or_404(
        Staff.objects.select_related("user"),
        pk=pk,
    )

    if request.method == "POST":

        with transaction.atomic():

            staff.is_active = False
            staff.save(
                update_fields=[
                    "is_active",
                    "updated_at",
                ]
            )

            if staff.user:
                staff.user.is_active = False
                staff.user.save(
                    update_fields=[
                        "is_active",
                        "updated_at",
                    ]
                )

        messages.success(
            request,
            f'Staff "{staff.first_name} {staff.last_name}" was deactivated successfully.',
        )

    return redirect("admin_web:staff_list")


def staff_activate(request, pk):

    staff = get_object_or_404(
        Staff.objects.select_related("user"),
        pk=pk,
    )

    if request.method == "POST":

        with transaction.atomic():

            staff.is_active = True
            staff.save(
                update_fields=[
                    "is_active",
                    "updated_at",
                ]
            )

            if staff.user:
                staff.user.is_active = True
                staff.user.save(
                    update_fields=[
                        "is_active",
                        "updated_at",
                    ]
                )

        messages.success(
            request,
            f'Staff "{staff.first_name} {staff.last_name}" was activated successfully.',
        )

    return redirect("admin_web:staff_list")


