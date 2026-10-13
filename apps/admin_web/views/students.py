import csv
import io
from datetime import date, datetime
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods
from ..views_common import *
from ..import_export import make_xlsx, read_rows

IMPORT_COLUMNS = [
    "first_name", "middle_name", "last_name", "nickname", "date_of_birth",
    "gender", "address", "enroll_date", "status", "branch_id", "class_id",
]

def _parse_date(value, field):
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError(f"{field} must use YYYY-MM-DD format.")

def _validate_student_rows(rows):
    errors = []
    valid = []
    genders = dict(Student.GENDER_CHOICES)
    statuses = dict(Student.STATUS_CHOICES)
    branch_ids = set(Branch.objects.filter(is_active=True).values_list("pk", flat=True))
    class_map = {str(pk): branch_id for pk, branch_id in Class.objects.values_list("pk", "branch_id")}
    for number, row in enumerate(rows, start=2):
        try:
            for field in ("first_name", "last_name", "date_of_birth", "gender", "enroll_date", "branch_id"):
                if not str(row.get(field, "")).strip():
                    raise ValueError(f"{field} is required.")
            branch_id = int(str(row["branch_id"]).strip())
            if branch_id not in branch_ids:
                raise ValueError("branch_id does not refer to an active branch.")
            gender = str(row["gender"]).strip().lower()
            if gender not in genders:
                raise ValueError("gender must be male, female, or other.")
            status = str(row.get("status") or "active").strip().lower()
            if status not in statuses:
                raise ValueError("status is invalid.")
            class_id = str(row.get("class_id") or "").strip()
            if class_id:
                if class_id not in class_map:
                    raise ValueError("class_id does not exist.")
                if class_map[class_id] != branch_id:
                    raise ValueError("class_id does not belong to branch_id.")
            valid.append({**row, "branch_id": branch_id, "class_id": int(class_id) if class_id else None,
                          "date_of_birth": _parse_date(row["date_of_birth"], "date_of_birth"),
                          "enroll_date": _parse_date(row["enroll_date"], "enroll_date"),
                          "gender": gender, "status": status})
        except (ValueError, TypeError) as exc:
            errors.append({"row": number, "error": str(exc)})
    return valid, errors

@login_required(login_url="admin_web:login")
@require_http_methods(["GET", "POST"])
def student_import(request):
    result = None
    if request.method == "POST":
        try:
            if request.POST.get("confirm") == "1":
                valid = request.session.pop("student_import_valid", [])
                errors = request.session.pop("student_import_errors", [])
                if errors or not valid:
                    raise ValueError("The validated import is no longer available. Upload the file again.")
            else:
                rows = read_rows(request.FILES["file"])
                valid, errors = _validate_student_rows(rows)
                request.session["student_import_valid"] = [
                    {**row, "date_of_birth": row["date_of_birth"].isoformat(), "enroll_date": row["enroll_date"].isoformat()}
                    for row in valid
                ]
                request.session["student_import_errors"] = errors
                request.session.modified = True
            if not errors and request.POST.get("confirm") == "1":
                for row in valid:
                    row["date_of_birth"] = _parse_date(row["date_of_birth"], "date_of_birth")
                    row["enroll_date"] = _parse_date(row["enroll_date"], "enroll_date")
                with transaction.atomic():
                    for row in valid:
                        student = Student.objects.create(**{field: row.get(field) for field in (
                            "first_name", "middle_name", "last_name", "nickname", "date_of_birth",
                            "gender", "address", "enroll_date", "status", "branch_id")})
                        if row["class_id"]:
                            ClassStudent.objects.create(student=student, class_obj_id=row["class_id"], is_current=True)
                messages.success(request, f"Imported {len(valid)} students.")
                return redirect("admin_web:student_list")
            result = {"total": len(rows), "valid": valid, "errors": errors}
        except (KeyError, ValueError, TypeError) as exc:
            result = {"total": 0, "valid": [], "errors": [{"row": "-", "error": str(exc)}]}
    return render(request, "admin_web/students/import.html", {"result": result, "columns": IMPORT_COLUMNS})

@login_required(login_url="admin_web:login")
def student_export(request):
    students = Student.objects.select_related("branch__school").prefetch_related(
        Prefetch("class_students", queryset=ClassStudent.objects.filter(is_current=True).select_related("class_obj"), to_attr="current_enrollments")
    ).order_by("last_name", "first_name")
    if request.GET.get("branch"):
        students = students.filter(branch_id=request.GET["branch"])
    headers = IMPORT_COLUMNS + ["branch_name", "school_name"]
    data = []
    for student in students:
        assignment = student.current_enrollments[0] if student.current_enrollments else None
        data.append([getattr(student, field, "") for field in IMPORT_COLUMNS[:9]] + [
            student.branch_id or "", assignment.class_obj_id if assignment else "",
            student.branch.name if student.branch else "", student.branch.school.name if student.branch else "",
        ])
    if request.GET.get("format", "csv").lower() == "xlsx":
        response = HttpResponse(make_xlsx(headers, data), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="students.xlsx"'
    else:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(data)
        response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="students.csv"'
    return response

@login_required(login_url="admin_web:login")
def student_detail(request, pk):
    student = get_object_or_404(
        Student.objects.prefetch_related(
            "student_guardians__guardian__user",
            "class_students__class_obj__branch__school",
            "class_students__class_obj__academic_year",
        ),
        pk=pk,
    )
    current_assignment = next(
        (assignment for assignment in student.class_students.all() if assignment.is_current),
        None,
    )
    location = Location.objects.filter(pk=student.location_id).first()
    return render(
        request,
        "admin_web/students/detail.html",
        {
            "student": student,
            "current_assignment": current_assignment,
            "location": location,
        },
    )


@login_required(login_url="admin_web:login")
def student_form(request, pk=None):
    student = get_object_or_404(Student, pk=pk) if pk else None
    form = StudentForm(request.POST or None, instance=student)
    guardian_formset = StudentGuardianFormSet(
        request.POST or None,
        instance=student,
        prefix="guardians",
    )
    if request.method == "POST" and form.is_valid() and guardian_formset.is_valid():
        with transaction.atomic():
            student = form.save()
            guardian_formset.instance = student
            guardian_formset.save()

            current_class = form.cleaned_data.get("current_class")
            ClassStudent.objects.filter(student=student, is_current=True).update(
                is_current=False
            )
            if current_class:
                assignment, _ = ClassStudent.objects.get_or_create(
                    student=student,
                    class_obj=current_class,
                    defaults={"is_current": True},
                )
                if not assignment.is_current:
                    assignment.is_current = True
                    assignment.save(update_fields=["is_current"])
            ClassStudent.ensure_current_for_student(student)
        messages.success(request, "Student saved.")
        return redirect("admin_web:student_detail", pk=student.pk)
    return render(
        request,
        "admin_web/students/form.html",
        {"form": form, "guardian_formset": guardian_formset, "student": student},
    )


@login_required(login_url="admin_web:login")
def student_delete(request, pk):
    student = get_object_or_404(Student, pk=pk)
    if request.method == "POST":
        try:
            student.delete()
            messages.success(request, "Student deleted.")
        except ProtectedError:
            messages.error(request, "This student has invoice history and cannot be deleted.")
        return redirect("admin_web:student_list")
    return redirect("admin_web:student_detail", pk=pk)


@login_required(login_url="admin_web:login")
def student_list(request):
    current_classes = ClassStudent.objects.filter(is_current=True).select_related(
        "class_obj__branch__school", "class_obj__academic_year"
    )
    students = Student.objects.prefetch_related(
        "student_guardians",
        Prefetch("class_students", queryset=current_classes, to_attr="current_enrollments"),
    ).order_by("last_name", "first_name")
    search = request.GET.get("q", "").strip()
    school_id = request.GET.get("school", "")
    branch_id = request.GET.get("branch", "")
    class_id = request.GET.get("class_obj", "")
    status = request.GET.get("status", "")
    if search:
        students = students.filter(
            Q(first_name__icontains=search)
            | Q(middle_name__icontains=search)
            | Q(last_name__icontains=search)
        )
    if school_id:
        students = students.filter(class_students__class_obj__branch__school_id=school_id)
    if branch_id:
        students = students.filter(branch_id=branch_id)
    if class_id:
        students = students.filter(class_students__class_obj_id=class_id)
    if status in dict(Student.STATUS_CHOICES):
        students = students.filter(status=status)
    students = students.distinct()
    page_obj = paginate_admin(students, request)
    return render(
        request,
        "admin_web/students/list.html",
        {
            "page_obj": page_obj, "search": search,
            "school_id": school_id, "branch_id": branch_id, "class_id": class_id, "status": status,
            "schools": School.objects.order_by("name"),
            "branches": Branch.objects.select_related("school").order_by("school__name", "name"),
            "classes": Class.objects.select_related("branch__school").order_by("branch__school__name", "branch__name", "name"),
            "statuses": Student.STATUS_CHOICES,
        },
    )


