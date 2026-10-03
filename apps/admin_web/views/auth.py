from ..views_common import *
from django.db.models import Sum
from datetime import date

from functools import wraps
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden

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


@login_required(login_url="admin_web:login")
def logout_view(request):
    """
    Destroy the current Django session.
    """

    logout(request)

    return redirect("admin_web:login")


@login_required(login_url="admin_web:login")
def dashboard(request):
    """Platform-wide operational dashboard for the platform administrator."""
    school_id = request.GET.get("school", "")
    period = request.GET.get("period", "all")
    school_filter = {"school_id": school_id} if school_id else {}
    class_filter = {"class_obj__branch__school_id": school_id} if school_id else {}
    student_filter = {"class_students__class_obj__branch__school_id": school_id} if school_id else {}
    invoice_filter = {"class_student__class_obj__branch__school_id": school_id} if school_id else {}

    schools = School.objects.all()
    branches = Branch.objects.filter(**school_filter)
    classes = Class.objects.filter(**{"branch__school_id": school_id} if school_id else {})
    students = Student.objects.filter(**student_filter).distinct()
    users = User.objects.all()
    staff = Staff.objects.filter(**{"branch__school_id": school_id} if school_id else {})
    guardians = Guardian.objects.filter(student_guardians__student__in=students).distinct()
    invoices = StudentInvoice.objects.filter(**invoice_filter)
    payments = Payment.objects.filter(student_invoice__in=invoices)

    if period == "month":
        invoices = invoices.filter(invoice_date__gte=timezone.localdate().replace(day=1))
        payments = payments.filter(student_invoice__in=invoices)
    elif period == "year":
        invoices = invoices.filter(invoice_date__gte=date(timezone.localdate().year, 1, 1))
        payments = payments.filter(student_invoice__in=invoices)

    if school_id:
        schools = schools.filter(pk=school_id)

    recent_payments = payments.select_related(
        "student_invoice__class_student__student",
        "student_invoice__class_student__class_obj__branch__school",
    ).order_by("-updated_at")[:8]
    paid_total = invoices.filter(status=StudentInvoice.Status.PAID).aggregate(
        total=Sum("amount_paid")
    )["total"] or 0
    invoiced_total = invoices.aggregate(total=Sum("total_amount"))["total"] or 0

    return render(request, "admin_web/dashboard.html", {
        "schools": schools.order_by("name"),
        "school_id": school_id,
        "period": period,
        "stats": {
            "schools": schools.count(), "active_schools": schools.filter(is_active=True).count(),
            "branches": branches.count(), "users": users.count(), "students": students.count(),
            "staff": staff.count(), "guardians": guardians.count(), "classes": classes.count(),
        },
        "billing": {
            "invoices": invoices.count(), "paid": invoices.filter(status=StudentInvoice.Status.PAID).count(),
            "outstanding": invoices.filter(status=StudentInvoice.Status.UNPAID).count(),
            "overdue": invoices.filter(status=StudentInvoice.Status.OVERDUE).count(),
            "submitted": payments.filter(status=Payment.Status.SUBMITTED).count(),
            "invoiced_total": invoiced_total, "paid_total": paid_total,
        },
        "recent_payments": recent_payments,
    })
