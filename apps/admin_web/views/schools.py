from ..views_common import *

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
    page_obj = paginate_admin(schools, request)

    return render(
        request,
        "admin_web/schools/list.html",
        {
            "page_obj": page_obj,
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
        School.objects.prefetch_related("branches__location__parent"),
        pk=pk,
    )
    branch_rows = []
    for branch in school.branches.all():
        location_path = " / ".join(
            location.name
            for location in branch.location.get_ancestors(include_self=True)
        )
        branch_rows.append({"branch": branch, "location_path": location_path})
    classes = (
        Class.objects.filter(branch__school=school)
        .select_related("branch", "academic_year")
        .annotate(student_count=Count("class_students", distinct=True))
        .prefetch_related("class_teachers__staff")
        .order_by("branch__name", "name")
    )

    return render(
        request,
        "admin_web/schools/detail.html",
        {
            "school": school,
            "branch_rows": branch_rows,
            "classes": classes,
        },
    )


@login_required(login_url="admin_web:login")
def school_form(request, pk=None):
    school = get_object_or_404(School, pk=pk) if pk else None
    form = SchoolForm(request.POST or None, request.FILES or None, instance=school)
    if request.method == "POST" and form.is_valid():
        school = form.save()
        messages.success(request, "School saved.")
        return redirect("admin_web:school_detail", pk=school.pk)
    return render(
        request,
        "admin_web/schools/form.html",
        {"form": form, "school": school, "is_edit": bool(school)},
    )


@login_required(login_url="admin_web:login")
def school_set_active(request, pk, active):
    school = get_object_or_404(School, pk=pk)
    if request.method == "POST":
        school.is_active = active
        school.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "School status updated.")
    return redirect("admin_web:school_detail", pk=pk)


@login_required(login_url="admin_web:login")
def class_detail(request, pk):
    class_obj = get_object_or_404(
        Class.objects.select_related("branch__school", "academic_year").prefetch_related(
            "class_students__student", "class_teachers__staff"
        ),
        pk=pk,
    )
    return render(
        request,
        "admin_web/schools/class_detail.html",
        {"class_obj": class_obj},
    )


@login_required(login_url="admin_web:login")
def class_form(request, school_pk, pk=None):
    school = get_object_or_404(School, pk=school_pk)
    class_obj = get_object_or_404(Class, pk=pk, branch__school=school) if pk else None
    form = ClassForm(request.POST or None, instance=class_obj)
    form.fields["branch"].queryset = Branch.objects.filter(school=school).order_by("name")
    form.fields["academic_year"].queryset = AcademicYear.objects.filter(
        branch__school=school
    ).select_related("branch").order_by("branch__name", "-start_date")
    branch = (
        form.data.get("branch")
        or request.GET.get("branch")
        or (class_obj.branch_id if class_obj else None)
    )
    if not branch and not class_obj:
        branch = Branch.objects.filter(school=school).order_by("name").values_list("pk", flat=True).first()
    teacher_formset = ClassTeacherFormSet(request.POST or None, prefix="teachers", form_kwargs={"branch": branch})
    student_formset = ClassStudentFormSet(request.POST or None, prefix="students", form_kwargs={"branch": branch})
    if not request.POST and class_obj:
        teacher_formset = ClassTeacherFormSet(initial=[{"staff": x.staff_id} for x in class_obj.class_teachers.all()], prefix="teachers", form_kwargs={"branch": class_obj.branch_id})
        student_formset = ClassStudentFormSet(initial=[{"student": x.student_id, "is_current": x.is_current} for x in class_obj.class_students.all()], prefix="students", form_kwargs={"branch": class_obj.branch_id})
    if request.method == "POST" and form.is_valid() and teacher_formset.is_valid() and student_formset.is_valid():
        selected_students = []
        for row in student_formset.cleaned_data:
            if not row: continue
            if row.get("create_student"):
                selected_students.append(Student.objects.create(
                    first_name=row["first_name"], last_name=row["last_name"],
                    date_of_birth=row["date_of_birth"], gender=row["gender"],
                    enroll_date=row["enroll_date"], status=row.get("status") or "active",
                    branch=form.cleaned_data["branch"],
                ))
            elif row.get("student"):
                selected_students.append(row["student"])
        selected_ids = {student.pk for student in selected_students}
        existing_assignments = list(class_obj.class_students.all()) if class_obj else []
        removals = [
            assignment for assignment in existing_assignments
            if assignment.student_id not in selected_ids
        ]
        if any(assignment.invoices.exists() for assignment in removals):
            form.add_error(None, "Students with invoices cannot be removed from this class.")
        else:
            with transaction.atomic():
                class_obj = form.save()
                teacher_ids = set()
                for row in teacher_formset.cleaned_data:
                    if not row: continue
                    if row.get("create_teacher"):
                        user = User.objects.create_user(
                            email=row["email"],
                            password=None,
                            temporary_password=generate_temporary_password(),
                            first_name=row["first_name"],
                            last_name=row["last_name"],
                            role=User.Role.TEACHER,
                        )
                        staff = Staff.objects.create(user=user, branch=class_obj.branch, first_name=row["first_name"], last_name=row["last_name"], email=row["email"], staff_type=Staff.StaffType.TEACHER, hire_date=row["hire_date"], qualification=row["qualification"])
                    else:
                        staff = row.get("staff")
                    if staff: teacher_ids.add(staff.pk)
                ClassTeacher.objects.filter(class_obj=class_obj).exclude(
                    staff_id__in=teacher_ids
                ).delete()
                for staff_id in teacher_ids:
                    ClassTeacher.objects.get_or_create(class_obj=class_obj, staff_id=staff_id)

                current_ids = {row["student"].pk for row in student_formset.cleaned_data if row and row.get("student") and row.get("is_current")}
                current_ids.update(student.pk for row, student in zip(student_formset.cleaned_data, selected_students) if row and row.get("create_student") and row.get("is_current"))
                ClassStudent.objects.filter(class_obj=class_obj).exclude(
                    student_id__in=selected_ids
                ).delete()
                for student in selected_students:
                    if student.pk in current_ids:
                        ClassStudent.objects.filter(
                            student=student,
                            is_current=True,
                        ).exclude(class_obj=class_obj).update(is_current=False)
                    assignment, _ = ClassStudent.objects.get_or_create(
                        class_obj=class_obj,
                        student=student,
                        defaults={"is_current": student.pk in current_ids},
                    )
                    if assignment.is_current != (student.pk in current_ids):
                        assignment.is_current = student.pk in current_ids
                        assignment.save(update_fields=["is_current"])
                    ClassStudent.ensure_current_for_student(student)
            messages.success(request, "Class saved.")
            return redirect("admin_web:school_detail", pk=school.pk)
    return render(
        request,
        "admin_web/schools/class_form.html",
        {"school": school, "class_obj": class_obj, "form": form, "teacher_formset": teacher_formset, "student_formset": student_formset},
    )


@login_required(login_url="admin_web:login")
def class_delete(request, school_pk, pk):
    school = get_object_or_404(School, pk=school_pk)
    class_obj = get_object_or_404(Class, pk=pk, branch__school=school)
    if request.method == "POST":
        has_history = any((
            class_obj.class_students.exists(),
            class_obj.activities.exists(),
            class_obj.assessments.exists(),
            class_obj.fee_type_classes.exists(),
        ))
        if has_history:
            messages.error(request, "Classes with students, activities, assessments, or fees cannot be deleted.")
        else:
            class_obj.delete()
            messages.success(request, "Class deleted.")
    return redirect("admin_web:school_detail", pk=school.pk)


