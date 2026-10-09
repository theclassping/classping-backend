from ..views_common import *

@login_required(login_url="admin_web:login")
def activity_list(request):
    activities = Activity.objects.select_related(
        "class_obj__branch", "class_teacher__staff__user"
    ).prefetch_related("students")
    search = request.GET.get("q", "").strip()
    publish_status = request.GET.get("published", "")
    school_id = request.GET.get("school", "")
    branch_id = request.GET.get("branch", "")
    class_id = request.GET.get("class_obj", "")
    if search:
        activities = activities.filter(
            Q(name__icontains=search)
            | Q(class_obj__name__icontains=search)
            | Q(class_teacher__staff__user__first_name__icontains=search)
            | Q(class_teacher__staff__user__last_name__icontains=search)
        )
    if publish_status in ("true", "false"):
        activities = activities.filter(is_publish=publish_status == "true")
    if school_id:
        activities = activities.filter(class_obj__branch__school_id=school_id)
    if branch_id:
        activities = activities.filter(class_obj__branch_id=branch_id)
    if class_id:
        activities = activities.filter(class_obj_id=class_id)
    page_obj = paginate_admin(activities, request)
    return render(
        request,
        "admin_web/activities/list.html",
        {"page_obj": page_obj, "search": search, "publish_status": publish_status,
         "school_id": school_id, "branch_id": branch_id, "class_id": class_id,
         "schools": School.objects.order_by("name"),
         "branches": Branch.objects.select_related("school").order_by("school__name", "name"),
         "classes": Class.objects.select_related("branch__school").order_by("branch__school__name", "branch__name", "name")},
    )


@login_required(login_url="admin_web:login")
def activity_detail(request, pk):
    activity = get_object_or_404(
        Activity.objects.select_related(
            "class_obj__branch__school", "class_obj__academic_year",
            "class_teacher__staff__branch", "class_teacher__staff__user",
        ).prefetch_related("activity_students__student", "images"),
        pk=pk,
    )
    return render(request, "admin_web/activities/detail.html", {"activity": activity})


@login_required(login_url="admin_web:login")
def activity_form(request, pk=None):
    activity = get_object_or_404(Activity, pk=pk) if pk else None
    form = ActivityForm(request.POST or None, instance=activity)
    student_formset = ActivityStudentFormSet(
        request.POST or None,
        instance=activity,
        prefix="students",
    )
    image_formset = ActivityImageFormSet(
        request.POST or None,
        instance=activity,
        prefix="images",
    )
    if (
        request.method == "POST"
        and form.is_valid()
        and student_formset.is_valid()
        and image_formset.is_valid()
    ):
        with transaction.atomic():
            activity = form.save(commit=False)
            activity.save()
            student_formset.instance = activity
            student_formset.save()
            image_formset.instance = activity
            image_formset.save()
        messages.success(request, "Activity saved.")
        return redirect("admin_web:activity_list")
    return render(
        request,
        "admin_web/activities/form.html",
        {
            "form": form,
            "student_formset": student_formset,
            "image_formset": image_formset,
            "activity": activity,
        },
    )


@login_required(login_url="admin_web:login")
def activity_delete(request, pk):
    activity = get_object_or_404(Activity, pk=pk)
    if request.method == "POST":
        activity.delete()
        messages.success(request, "Activity deleted.")
    return redirect("admin_web:activity_list")


