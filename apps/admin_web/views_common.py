from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.db.models.deletion import ProtectedError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.http import HttpResponseForbidden, JsonResponse
from django.utils import timezone
from functools import wraps

from .forms import (
    AcademicYearForm,
    ActivityForm,
    ActivityImageFormSet,
    ActivityStudentFormSet,
    ClassForm,
    FeeTypeForm,
    GuardianForm,
    LocationForm,
    PaymentForm,
    PaymentProofFormSet,
    PaymentRejectionForm,
    ScoreSettingForm,
    SchoolForm,
    StudentForm,
    StudentGuardianFormSet,
)
from apps.academic_years.models import AcademicYear
from apps.activities.models import Activity
from apps.classes.models import Class, ClassStudent, ClassTeacher
from apps.fee_types.models import FeeType, FeeTypeClass
from apps.guardians.models import Guardian
from apps.locations.models import Location
from apps.payments.models import Payment
from apps.score_settings.models import LevelScore, NumericScore, ScoreSetting
from apps.student_invoices.models import StudentInvoice
from apps.staffs.models import Staff
from apps.schools.models import Branch, School
from apps.students.models import Student
from apps.users.managers import generate_temporary_password
from apps.users.models import API_MODULE_CHOICES, RoleModulePermission, User

ADMIN_PAGE_SIZE = 25

def paginate_admin(queryset, request, page_size=ADMIN_PAGE_SIZE):
    return Paginator(queryset, page_size).get_page(request.GET.get("page"))


def platform_admin_required(view_func):
    @wraps(view_func)
    @login_required(login_url="admin_web:login")
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_superuser:
            return HttpResponseForbidden()
        return view_func(request, *args, **kwargs)

    return wrapped_view


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


SETTINGS_MODULES = {
    "fee-types": {
        "title": "Fee Types",
        "model": FeeType,
        "form": FeeTypeForm,
        "queryset": lambda: FeeType.objects.select_related("branch__school"),
    },
    "locations": {
        "title": "Locations",
        "model": Location,
        "form": LocationForm,
        "queryset": lambda: Location.objects.select_related("parent"),
    },
    "academic-years": {
        "title": "Academic Years",
        "model": AcademicYear,
        "form": AcademicYearForm,
        "queryset": lambda: AcademicYear.objects.select_related("branch__school"),
    },
    "score-settings": {
        "title": "Score Settings",
        "model": ScoreSetting,
        "form": ScoreSettingForm,
        "queryset": lambda: ScoreSetting.objects.select_related(
            "branch__school"
        ).prefetch_related("level_scores"),
    },
}

