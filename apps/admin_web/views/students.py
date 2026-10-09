from ..views_common import *

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
        students = students.filter(class_students__class_obj__branch_id=branch_id)
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


