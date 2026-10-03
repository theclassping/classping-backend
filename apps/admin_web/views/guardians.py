from ..views_common import *

@login_required(login_url="admin_web:login")
def guardian_list(request):
    guardians = Guardian.objects.prefetch_related("student_guardians").order_by("name")
    search = request.GET.get("q", "").strip()
    if search:
        guardians = guardians.filter(
            Q(name__icontains=search)
            | Q(email__icontains=search)
            | Q(phone_number__icontains=search)
        )
    page_obj = Paginator(guardians, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "admin_web/guardians/list.html",
        {"page_obj": page_obj, "search": search},
    )


@login_required(login_url="admin_web:login")
def guardian_detail(request, pk):
    guardian = get_object_or_404(
        Guardian.objects.select_related("user").prefetch_related(
            "student_guardians__student"
        ),
        pk=pk,
    )
    return render(
        request,
        "admin_web/guardians/detail.html",
        {"guardian": guardian},
    )


@login_required(login_url="admin_web:login")
def guardian_form(request, pk=None):
    guardian = get_object_or_404(Guardian, pk=pk) if pk else None
    form = GuardianForm(request.POST or None, instance=guardian)
    if request.method == "POST" and form.is_valid():
        guardian = form.save()
        messages.success(request, "Guardian saved.")
        return redirect("admin_web:guardian_detail", pk=guardian.pk)
    return render(
        request,
        "admin_web/guardians/form.html",
        {"form": form, "guardian": guardian},
    )


@login_required(login_url="admin_web:login")
def guardian_delete(request, pk):
    guardian = get_object_or_404(Guardian, pk=pk)
    if request.method == "POST":
        guardian.delete()
        messages.success(request, "Guardian deleted. Its Parent user account was kept.")
        return redirect("admin_web:guardian_list")
    return redirect("admin_web:guardian_detail", pk=pk)


