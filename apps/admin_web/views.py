from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse

from apps.locations.models import Location
from apps.staffs.models import Staff
from apps.schools.models import Branch, School
from apps.users.models import User


def login_view(request):
    """
    Handle Admin Web login.

    We use Django session authentication for the
    template-based Admin Web.

    This is independent from the JWT authentication
    used by the REST API.
    """

    if request.user.is_authenticated:
        return redirect("admin_web:dashboard")

    if request.method == "POST":

        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=email,
            password=password,
        )

        if user is not None:

            login(request, user)

            return redirect("admin_web:dashboard")

        return render(
            request,
            "admin_web/login.html",
            {
                "error": "Invalid email or password.",
                "email": email,
            },
        )

    return render(
        request,
        "admin_web/login.html",
    )


def logout_view(request):
    """
    Destroy the current Django session.
    """

    logout(request)

    return redirect("admin_web:login")


@login_required(login_url="admin_web:login")
def dashboard(request):
    """
    Admin Web dashboard.

    For now, redirect to School Management.
    """

    return redirect("admin_web:school_list")


@login_required(login_url="admin_web:login")
def school_list(request):
    """
    Display all schools.

    select_related/prefetch_related is useful when
    we later display branch information.
    """

    schools = (
        School.objects
        .prefetch_related("branches")
        .order_by("name")
    )

    return render(
        request,
        "admin_web/schools/list.html",
        {
            "schools": schools,
        },
    )


@login_required(login_url="admin_web:login")
def school_create(request):
    """
    Create a new school.

    For now this creates only the School.
    Branch management will be handled separately.
    """

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        register_number = request.POST.get(
            "register_number",
            "",
        ).strip()

        is_active = request.POST.get("is_active") == "on"

        # Basic validation.
        errors = []

        if not name:
            errors.append("School name is required.")

        if not register_number:
            errors.append(
                "Register number is required."
            )

        # Check duplicate register number.
        if (
            register_number
            and School.objects.filter(
                register_number=register_number
            ).exists()
        ):
            errors.append(
                "Register number already exists."
            )

        if errors:

            return render(
                request,
                "admin_web/schools/form.html",
                {
                    "errors": errors,
                    "name": name,
                    "register_number": register_number,
                    "is_active": is_active,
                },
            )

        school = School.objects.create(
            name=name,
            register_number=register_number,
            is_active=is_active,
        )

        return redirect(
            "admin_web:school_detail",
            pk=school.pk,
        )

    return render(
        request,
        "admin_web/schools/form.html",
        {
            "is_active": True,
        },
    )


@login_required(login_url="admin_web:login")
def school_detail(request, pk):
    """
    Display one school and its branches.
    """

    school = get_object_or_404(
        School.objects.prefetch_related("branches"),
        pk=pk,
    )

    return render(
        request,
        "admin_web/schools/detail.html",
        {
            "school": school,
        },
    )

@login_required(login_url="admin_web:login")
def school_edit(request, pk):
    """
    Edit an existing school.

    This updates only the basic School information.

    Branches and school images will be managed separately.
    """

    # Get the school or return HTTP 404 if it doesn't exist.
    school = get_object_or_404(
        School,
        pk=pk,
    )

    if request.method == "POST":

        # Read submitted values.
        name = request.POST.get(
            "name",
            "",
        ).strip()

        register_number = request.POST.get(
            "register_number",
            "",
        ).strip()

        is_active = request.POST.get(
            "is_active"
        ) == "on"

        # Store validation errors here.
        errors = []

        # -------------------------------------------------
        # Validation
        # -------------------------------------------------

        if not name:
            errors.append(
                "School name is required."
            )

        if not register_number:
            errors.append(
                "Register number is required."
            )

        # Check whether another school already uses
        # this register number.
        #
        # IMPORTANT:
        # Exclude the current school from this check.
        if (
            register_number
            and School.objects
            .filter(
                register_number=register_number
            )
            .exclude(
                pk=school.pk
            )
            .exists()
        ):
            errors.append(
                "Register number already exists."
            )

        # -------------------------------------------------
        # Validation failed
        # -------------------------------------------------

        if errors:

            return render(
                request,
                "admin_web/schools/form.html",
                {
                    "school": school,
                    "errors": errors,
                    "name": name,
                    "register_number": register_number,
                    "is_active": is_active,
                    "is_edit": True,
                },
            )

        # -------------------------------------------------
        # Update database
        # -------------------------------------------------

        school.name = name
        school.register_number = register_number
        school.is_active = is_active

        school.save()

        # Redirect back to the school detail page.
        return redirect(
            "admin_web:school_detail",
            pk=school.pk,
        )

    # -----------------------------------------------------
    # GET request
    # -----------------------------------------------------

    return render(
        request,
        "admin_web/schools/form.html",
        {
            "school": school,

            # Populate the form with existing values.
            "name": school.name,
            "register_number": school.register_number,
            "is_active": school.is_active,

            # Used by the template to know this is edit mode.
            "is_edit": True,
        },
    )

@login_required(login_url="admin_web:login")
def branch_create(request, school_pk):
    """
    Create a new branch for a school.

    The Branch model stores only one Location FK.

    The form displays the location hierarchy as:
        Province
            ↓
        City / Regency
            ↓
        District
            ↓
        Village

    The selected Village/District/City/Province location ID
    will eventually be stored in Branch.location.
    """

    school = get_object_or_404(School, pk=school_pk)

    # ---------------------------------------------------------
    # GET initial locations
    # ---------------------------------------------------------
    #
    # We only need Province-level locations initially.
    #
    # In your Location model:
    #
    # COUNTRY
    #   └── PROVINCE
    #        └── CITY
    #             └── DISTRICT
    #                  └── VILLAGE
    #
    provinces = (
        Location.objects
        .filter(location_type="PROVINCE")
        .order_by("name")
    )

    if request.method == "POST":

        # -----------------------------------------------------
        # Get normal Branch fields
        # -----------------------------------------------------

        name = request.POST.get("name", "").strip()
        code = request.POST.get("code", "").strip()
        address = request.POST.get("address", "").strip()
        phone = request.POST.get("phone", "").strip()
        email = request.POST.get("email", "").strip()
        is_active = request.POST.get("is_active") == "on"

        # -----------------------------------------------------
        # Get selected location
        # -----------------------------------------------------
        #
        # The frontend will submit the most specific selected
        # location through "location_id".
        #
        location_id = request.POST.get("location_id", "").strip()

        errors = []
        location = None

        # -----------------------------------------------------
        # Validate Branch Name
        # -----------------------------------------------------

        if not name:
            errors.append("Branch name is required.")

        # -----------------------------------------------------
        # Validate Branch Code
        # -----------------------------------------------------

        if not code:
            errors.append("Branch code is required.")

        # -----------------------------------------------------
        # Validate Location
        # -----------------------------------------------------

        if not location_id:
            errors.append("Location is required.")
        else:
            try:
                location = Location.objects.get(pk=location_id)

            except (Location.DoesNotExist, ValueError):
                errors.append("Invalid location.")

        # -----------------------------------------------------
        # Validate duplicate Branch code
        # -----------------------------------------------------

        if (
            code
            and Branch.objects.filter(
                school=school,
                code=code,
            ).exists()
        ):
            errors.append(
                "Branch code already exists for this school."
            )

        # -----------------------------------------------------
        # If validation failed
        # -----------------------------------------------------

        if errors:
            return render(
                request,
                "admin_web/branches/form.html",
                {
                    "school": school,

                    # Location data
                    "provinces": provinces,

                    # Preserve selected location
                    "location_id": location_id,

                    # Branch data
                    "errors": errors,
                    "name": name,
                    "code": code,
                    "address": address,
                    "phone": phone,
                    "email": email,
                    "is_active": is_active,
                },
            )

        # -----------------------------------------------------
        # Create Branch
        # -----------------------------------------------------

        Branch.objects.create(
            school=school,
            name=name,
            code=code,
            address=address,
            phone=phone,
            email=email,
            location=location,
            is_active=is_active,
        )

        # -----------------------------------------------------
        # Go back to School Detail
        # -----------------------------------------------------

        return redirect(
            "admin_web:school_detail",
            pk=school.pk,
        )

    # ---------------------------------------------------------
    # GET request
    # ---------------------------------------------------------

    return render(
        request,
        "admin_web/branches/form.html",
        {
            "school": school,
            "provinces": provinces,
            "is_active": True,
        },
    )
    
@login_required(login_url="admin_web:login")
def branch_edit(request, school_pk, pk):
    """
    Edit an existing Branch.

    The location is selected through:

        Province
            ↓
        City / Regency
            ↓
        District
            ↓
        Village

    Only the final selected Location is stored in Branch.location.
    """

    # ---------------------------------------------------------
    # Get school
    # ---------------------------------------------------------

    school = get_object_or_404(
        School,
        pk=school_pk,
    )

    # ---------------------------------------------------------
    # Get branch
    #
    # We also make sure the branch belongs to this school.
    # ---------------------------------------------------------

    branch = get_object_or_404(
        Branch,
        pk=pk,
        school=school,
    )

    # ---------------------------------------------------------
    # Get all provinces
    # ---------------------------------------------------------

    provinces = (
        Location.objects
        .filter(location_type="PROVINCE")
        .order_by("name")
    )

    # ---------------------------------------------------------
    # Existing location
    # ---------------------------------------------------------

    current_location = branch.location

    # These values are used to pre-select the location hierarchy.
    #
    # Example:
    #
    # Province  = Jawa Barat
    # City      = Kota Bandung
    # District  = Lengkong
    # Village   = Lingkar Selatan
    #
    # We walk upward through the MPTT parent relationship.

    selected_province_id = ""
    selected_city_id = ""
    selected_district_id = ""
    selected_village_id = ""

    if current_location:

        location = current_location

        # -----------------------------------------------------
        # Village
        # -----------------------------------------------------

        if location.location_type == "VILLAGE":

            selected_village_id = location.id

            location = location.parent

        # -----------------------------------------------------
        # District
        # -----------------------------------------------------

        if location and location.location_type == "DISTRICT":

            selected_district_id = location.id

            location = location.parent

        # -----------------------------------------------------
        # City
        # -----------------------------------------------------

        if location and location.location_type == "CITY":

            selected_city_id = location.id

            location = location.parent

        # -----------------------------------------------------
        # Province
        # -----------------------------------------------------

        if location and location.location_type == "PROVINCE":

            selected_province_id = location.id

    # ---------------------------------------------------------
    # POST
    # ---------------------------------------------------------

    if request.method == "POST":

        name = request.POST.get(
            "name",
            "",
        ).strip()

        code = request.POST.get(
            "code",
            "",
        ).strip()

        address = request.POST.get(
            "address",
            "",
        ).strip()

        phone = request.POST.get(
            "phone",
            "",
        ).strip()

        email = request.POST.get(
            "email",
            "",
        ).strip()

        is_active = (
            request.POST.get("is_active") == "on"
        )

        location_id = request.POST.get(
            "location_id",
            "",
        ).strip()

        # -----------------------------------------------------
        # Get selected hierarchy IDs
        #
        # These are mainly useful for re-rendering the form
        # if validation fails.
        # -----------------------------------------------------

        selected_province_id = request.POST.get(
            "province_id",
            "",
        )

        selected_city_id = request.POST.get(
            "city_id",
            "",
        )

        selected_district_id = request.POST.get(
            "district_id",
            "",
        )

        selected_village_id = request.POST.get(
            "village_id",
            "",
        )

        errors = []
        location = None

        # -----------------------------------------------------
        # Validate name
        # -----------------------------------------------------

        if not name:
            errors.append(
                "Branch name is required."
            )

        # -----------------------------------------------------
        # Validate code
        # -----------------------------------------------------

        if not code:
            errors.append(
                "Branch code is required."
            )

        # -----------------------------------------------------
        # Validate duplicate code
        # -----------------------------------------------------

        if (
            code
            and Branch.objects.filter(
                school=school,
                code=code,
            )
            .exclude(pk=branch.pk)
            .exists()
        ):
            errors.append(
                "Branch code already exists for this school."
            )

        # -----------------------------------------------------
        # Validate location
        # -----------------------------------------------------

        if not location_id:

            errors.append(
                "Location is required."
            )

        else:

            try:

                location = Location.objects.get(
                    pk=location_id
                )

            except (
                Location.DoesNotExist,
                ValueError,
            ):

                errors.append(
                    "Invalid location."
                )

        # -----------------------------------------------------
        # Validation failed
        # -----------------------------------------------------

        if errors:

            return render(
                request,
                "admin_web/branches/form.html",
                {
                    "school": school,
                    "branch": branch,

                    "provinces": provinces,

                    "errors": errors,

                    "name": name,
                    "code": code,
                    "address": address,
                    "phone": phone,
                    "email": email,
                    "is_active": is_active,

                    "location_id": location_id,

                    "selected_province_id":
                        selected_province_id,

                    "selected_city_id":
                        selected_city_id,

                    "selected_district_id":
                        selected_district_id,

                    "selected_village_id":
                        selected_village_id,

                    "is_edit": True,
                },
            )

        # -----------------------------------------------------
        # Update Branch
        # -----------------------------------------------------

        branch.name = name
        branch.code = code
        branch.address = address
        branch.phone = phone
        branch.email = email
        branch.location = location
        branch.is_active = is_active

        branch.save()

        # -----------------------------------------------------
        # Success message
        # -----------------------------------------------------

        messages.success(
            request,
            f'Branch "{branch.name}" was updated successfully.',
        )

        # -----------------------------------------------------
        # Back to School Detail
        # -----------------------------------------------------

        return redirect(
            "admin_web:school_detail",
            pk=school.pk,
        )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    return render(
        request,
        "admin_web/branches/form.html",
        {
            "school": school,
            "branch": branch,

            "provinces": provinces,

            "name": branch.name,
            "code": branch.code,
            "address": branch.address,
            "phone": branch.phone,
            "email": branch.email,
            "is_active": branch.is_active,

            "location_id": (
                branch.location_id
                if branch.location_id
                else ""
            ),

            "selected_province_id":
                selected_province_id,

            "selected_city_id":
                selected_city_id,

            "selected_district_id":
                selected_district_id,

            "selected_village_id":
                selected_village_id,

            "is_edit": True,
        },
    )

@login_required(login_url="admin_web:login")
def branch_deactivate(request, school_pk, pk):
    """
    Deactivate a Branch.

    We do NOT delete the branch.

    Instead:

        branch.is_active = False

    This preserves historical data such as:
        - students
        - classes
        - invoices
        - payments
        - reports

    Only POST requests are allowed.
    """

    # ---------------------------------------------------------
    # Get school
    # ---------------------------------------------------------

    school = get_object_or_404(
        School,
        pk=school_pk,
    )

    # ---------------------------------------------------------
    # Get branch belonging to this school
    # ---------------------------------------------------------

    branch = get_object_or_404(
        Branch,
        pk=pk,
        school=school,
    )

    # ---------------------------------------------------------
    # Only POST can deactivate
    # ---------------------------------------------------------

    if request.method != "POST":

        return redirect(
            "admin_web:school_detail",
            pk=school.pk,
        )

    # ---------------------------------------------------------
    # Deactivate
    # ---------------------------------------------------------

    branch.is_active = False

    branch.save(
        update_fields=[
            "is_active",
            "updated_at",
        ]
    )

    # ---------------------------------------------------------
    # Success message
    # ---------------------------------------------------------

    messages.success(
        request,
        f'Branch "{branch.name}" was deactivated successfully.',
    )

    # ---------------------------------------------------------
    # Back to School Detail
    # ---------------------------------------------------------

    return redirect(
        "admin_web:school_detail",
        pk=school.pk,
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

    users = (
        User.objects
        .all()
        .order_by("-created_at")
    )

    return render(
        request,
        "admin_web/users/list.html",
        {
            "users": users,
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
def staff_list(request):
    """
    Display all staff members.

    We use select_related() because Staff has ForeignKey/OneToOne
    relationships with Branch and User.
    """

    staffs = (
        Staff.objects
        .select_related(
            "branch",
            "branch__school",
            "user",
        )
        .order_by("first_name", "last_name")
    )

    return render(
        request,
        "admin_web/staff/list.html",
        {
            "staffs": staffs,
        },
    )

@login_required(login_url="admin_web:login")
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

        if not password:
            errors.append("Password is required.")

        if password != confirm_password:
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
                user = User(
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    role=user_role,
                    is_active=is_active,
                )

                user.set_password(password)
                user.save()

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

@login_required(login_url="admin_web:login")
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
                    # We only create a User if a password is provided.
                    # -------------------------------------------------

                    if password:

                        user = User(
                            email=email,
                            first_name=first_name,
                            last_name=last_name,
                            role=user_role,
                            is_active=is_active,
                        )

                        user.set_password(password)
                        user.save()

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

@login_required(login_url="admin_web:login")
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

@login_required(login_url="admin_web:login")
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