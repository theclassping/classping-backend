from decimal import Decimal, InvalidOperation

from django.conf import settings

from apps.uploads.usage import branch_storage_report, branches_by_usage

from ..views_common import *

GIB = 1024 ** 3
MAX_CAPACITY_GB = 1_000_000  # 1 PB; keeps the value well inside a bigint


def _parse_capacity_gb(raw):
    """Form value in GB -> (bytes or None for the default, error message or None)."""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    try:
        gigabytes = Decimal(raw)
    except InvalidOperation:
        return None, "Storage capacity must be a number of GB."
    if not gigabytes.is_finite() or gigabytes <= 0:
        return None, "Storage capacity must be greater than 0 GB."
    if gigabytes > MAX_CAPACITY_GB:
        return None, f"Storage capacity must be at most {MAX_CAPACITY_GB:,} GB."
    return int(gigabytes * GIB), None


def _capacity_gb(capacity_bytes):
    if capacity_bytes is None:
        return ""
    return f"{Decimal(capacity_bytes) / GIB:.2f}".rstrip("0").rstrip(".")


def _capacity_context(raw=""):
    return {
        "storage_capacity_gb": raw,
        "default_storage_gb": _capacity_gb(settings.DEFAULT_BRANCH_STORAGE_BYTES),
    }


def storage_overview(request):
    """Every branch's media storage, fullest first."""
    branches = Branch.objects.select_related("school")
    names = {branch.pk: branch.school.name for branch in branches}
    rows = branches_by_usage(branches)
    for row in rows:
        row["school_name"] = names.get(row["branch_id"], "")
    return render(request, "admin_web/branches/storage.html", {"rows": rows})

def branch_detail(request, school_pk, pk):
    school = get_object_or_404(School, pk=school_pk)
    branch = get_object_or_404(
        Branch.objects.select_related("location__parent").prefetch_related(
            "academic_years", "classes", "staffs"
        ),
        pk=pk,
        school=school,
    )
    location_path = " / ".join(
        location.name for location in branch.location.get_ancestors(include_self=True)
    )
    return render(
        request,
        "admin_web/schools/branch_detail.html",
        {
            "school": school,
            "branch": branch,
            "location_path": location_path,
            "storage": branch_storage_report(branch),
        },
    )


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
        storage_capacity_raw = request.POST.get("storage_capacity_gb", "")
        storage_capacity_bytes, capacity_error = _parse_capacity_gb(storage_capacity_raw)

        # -----------------------------------------------------
        # Get selected location
        # -----------------------------------------------------
        #
        # The frontend will submit the most specific selected
        # location through "location_id".
        #
        location_id = request.POST.get("location_id", "").strip()

        errors = [capacity_error] if capacity_error else []
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
                    **_capacity_context(storage_capacity_raw),
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
            storage_capacity_bytes=storage_capacity_bytes,
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
            **_capacity_context(),
        },
    )


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

        storage_capacity_raw = request.POST.get("storage_capacity_gb", "")
        if storage_capacity_raw.strip() == _capacity_gb(branch.storage_capacity_bytes):
            # Unchanged in the form: keep the exact bytes (the form shows a rounded GB value).
            storage_capacity_bytes, capacity_error = branch.storage_capacity_bytes, None
        else:
            storage_capacity_bytes, capacity_error = _parse_capacity_gb(storage_capacity_raw)

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

        errors = [capacity_error] if capacity_error else []
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

                    **_capacity_context(storage_capacity_raw),

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
        branch.storage_capacity_bytes = storage_capacity_bytes

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

            **_capacity_context(_capacity_gb(branch.storage_capacity_bytes)),

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


def branch_set_active(request, school_pk, pk, active):
    school = get_object_or_404(School, pk=school_pk)
    branch = get_object_or_404(Branch, pk=pk, school=school)
    if request.method == "POST":
        branch.is_active = active
        branch.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "Branch status updated.")
    return redirect("admin_web:school_detail", pk=school.pk)


