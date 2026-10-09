from ..views_common import *
from .auth import platform_admin_required

def _settings_module(section):
    module = SETTINGS_MODULES.get(section)
    if module is None:
        from django.http import Http404
        raise Http404("Settings module not found")
    return module


@login_required(login_url="admin_web:login")
def settings_detail(request, section, pk):
    module = _settings_module(section)
    obj = get_object_or_404(module["queryset"](), pk=pk)
    if section == "fee-types":
        details = [
            ("Branch", f"{obj.branch.school.name} / {obj.branch.name}"),
            ("Name", obj.name), ("Description", obj.description or "-"),
            ("Amount", f"{obj.amount} {obj.currency}"),
            ("Recurring", "Yes" if obj.is_recurring else "No"),
            ("Frequency", obj.get_recurring_frequency_display() if obj.recurring_frequency else "-"),
            ("Status", "Active" if obj.is_active else "Inactive"),
            (
                "Applicable classes",
                ", ".join(
                    obj.fee_type_classes.select_related("class_obj__academic_year")
                    .values_list("class_obj__name", flat=True)
                ) or "All classes in this branch",
            ),
        ]
    elif section == "locations":
        details = [
            ("Name", obj.name), ("Code", obj.code or "-"),
            ("Type", obj.get_location_type_display()),
            ("Parent", obj.parent.name if obj.parent else "Top level"),
        ]
    elif section == "academic-years":
        details = [
            ("Branch", f"{obj.branch.school.name} / {obj.branch.name}"),
            ("Name", obj.name), ("Start date", obj.start_date),
            ("End date", obj.end_date),
            ("Current", "Yes" if obj.is_current else "No"),
        ]
    else:
        details = [
            ("Branch", f"{obj.branch.school.name} / {obj.branch.name}"),
            ("Name", obj.name), ("Description", obj.description or "-"),
            ("Score type", obj.get_score_type_display()),
        ]
        if obj.score_type == ScoreSetting.ScoreType.NUMERIC:
            numeric = getattr(obj, "numeric_score", None)
            details.append((
                "Score range",
                f"{numeric.min_score} - {numeric.max_score}" if numeric else "-",
            ))
        else:
            details.append((
                "Levels",
                ", ".join(obj.level_scores.values_list("name", flat=True)) or "-",
            ))
    return render(
        request,
        "admin_web/settings/detail.html",
        {"module": module, "section": section, "object": obj, "details": details},
    )


@login_required(login_url="admin_web:login")
def settings_list(request, section):
    module = _settings_module(section)
    objects = module["queryset"]().order_by("pk")
    search = request.GET.get("q", "").strip()
    branch_id = request.GET.get("branch", "")
    option_type = request.GET.get("type", "")
    status = request.GET.get("status", "")
    parent_id = request.GET.get("parent", "")
    if search:
        if section == "locations":
            objects = objects.filter(Q(name__icontains=search) | Q(code__icontains=search))
        else:
            objects = objects.filter(Q(name__icontains=search) | Q(description__icontains=search))
    if branch_id and section in ("fee-types", "academic-years", "score-settings"):
        objects = objects.filter(branch_id=branch_id)
    if section == "fee-types":
        if status in ("true", "false"): objects = objects.filter(is_active=status == "true")
    elif section == "locations":
        if option_type: objects = objects.filter(location_type=option_type)
        if parent_id: objects = objects.filter(parent_id=parent_id)
    elif section == "academic-years" and status in ("true", "false"):
        objects = objects.filter(is_current=status == "true")
    elif section == "score-settings" and option_type:
        objects = objects.filter(score_type=option_type)
    rows = []
    for obj in objects:
        if section == "fee-types":
            primary, secondary = obj.name, f"{obj.amount} {obj.currency}"
            tertiary = f"{obj.branch.school.name} / {obj.branch.name}"
            status_label = "Active" if obj.is_active else "Inactive"
        elif section == "locations":
            primary, secondary = obj.name, obj.get_location_type_display()
            tertiary = obj.parent.name if obj.parent else "Top level"
            status_label = obj.code or "-"
        elif section == "academic-years":
            primary, secondary = obj.name, f"{obj.start_date} to {obj.end_date}"
            tertiary = f"{obj.branch.school.name} / {obj.branch.name}"
            status_label = "Current" if obj.is_current else "-"
        else:
            primary, secondary = obj.name, obj.get_score_type_display()
            tertiary = f"{obj.branch.school.name} / {obj.branch.name}"
            status_label = (
                f"{obj.numeric_score.min_score} - {obj.numeric_score.max_score}"
                if obj.score_type == ScoreSetting.ScoreType.NUMERIC
                and hasattr(obj, "numeric_score")
                else ", ".join(obj.level_scores.values_list("name", flat=True))
            )
        rows.append({
            "object": obj,
            "primary": primary,
            "secondary": secondary,
            "tertiary": tertiary,
            "status_label": status_label,
        })
    page_obj = paginate_admin(rows, request)
    return render(
        request,
        "admin_web/settings/list.html",
        {"section": section, "module": module, "page_obj": page_obj, "search": search,
         "branch_id": branch_id, "option_type": option_type, "status": status, "parent_id": parent_id,
         "branches": Branch.objects.select_related("school").order_by("school__name", "name"),
         "location_types": Location.TYPE_CHOICES,
         "locations": Location.objects.order_by("tree_id", "lft"),
         "score_types": ScoreSetting.ScoreType.choices},
    )


@login_required(login_url="admin_web:login")
def settings_form(request, section, pk=None):
    module = _settings_module(section)
    model = module["model"]
    instance = get_object_or_404(model, pk=pk) if pk else None
    form = module["form"](request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save()
            if section == "fee-types":
                selected_classes = form.cleaned_data["classes"]
                FeeTypeClass.objects.filter(fee_type=obj).exclude(
                    class_obj__in=selected_classes
                ).delete()
                for class_obj in selected_classes:
                    FeeTypeClass.objects.get_or_create(
                        fee_type=obj,
                        class_obj=class_obj,
                    )
            if section == "academic-years" and obj.is_current:
                AcademicYear.objects.filter(branch=obj.branch, is_current=True).exclude(
                    pk=obj.pk
                ).update(is_current=False)
            elif section == "score-settings":
                if obj.score_type == ScoreSetting.ScoreType.NUMERIC:
                    NumericScore.objects.update_or_create(
                        score_setting=obj,
                        defaults={
                            "min_score": form.cleaned_data["min_score"],
                            "max_score": form.cleaned_data["max_score"],
                        },
                    )
                    LevelScore.objects.filter(score_setting=obj).delete()
                else:
                    NumericScore.objects.filter(score_setting=obj).delete()
                    level_names = form.cleaned_data["level_names"]
                    existing = list(obj.level_scores.order_by("position"))
                    for score in existing:
                        score.name = f"__updating_{score.pk}"
                        score.save(update_fields=["name"])
                    for position, name in enumerate(level_names, start=1):
                        if position <= len(existing):
                            score = existing[position - 1]
                            score.name = name
                            score.position = position
                            score.save(update_fields=["name", "position"])
                        else:
                            LevelScore.objects.create(
                                score_setting=obj, name=name, position=position
                            )
                    LevelScore.objects.filter(
                        score_setting=obj, position__gt=len(level_names)
                    ).delete()
        messages.success(request, f"{module['title']} saved.")
        return redirect("admin_web:settings_list", section=section)
    return render(
        request,
        "admin_web/settings/form.html",
        {"section": section, "module": module, "form": form, "instance": instance},
    )


@login_required(login_url="admin_web:login")
def settings_delete(request, section, pk):
    if request.method != "POST":
        return redirect("admin_web:settings_list", section=section)
    module = _settings_module(section)
    obj = get_object_or_404(module["model"], pk=pk)
    try:
        if section == "fee-types":
            obj.is_active = False
            obj.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "Fee type deactivated; invoice history was preserved.")
        elif section == "locations":
            if (
                obj.children.exists()
                or obj.branches.exists()
                or Student.objects.filter(location_id=obj.pk).exists()
            ):
                messages.error(request, "Locations referenced by children, branches, or students cannot be deleted.")
            else:
                obj.delete()
                messages.success(request, "Location deleted.")
        elif section == "academic-years":
            if obj.classes.exists():
                messages.error(request, "Academic years used by classes cannot be deleted.")
            else:
                obj.delete()
                messages.success(request, "Academic year deleted.")
        else:
            if obj.indicators.exists() or obj.level_scores.filter(
                student_assessments__isnull=False
            ).exists():
                messages.error(request, "Score settings used by reports or assessments cannot be deleted.")
            else:
                obj.delete()
                messages.success(request, "Score setting deleted.")
    except ProtectedError:
        messages.error(request, "This record is still referenced and cannot be deleted.")
    return redirect("admin_web:settings_list", section=section)


@platform_admin_required
def role_permissions(request):
    role_values = User.Role.values
    selected_role = request.GET.get("role", User.Role.PARENT)
    errors = []

    if request.method == "POST":
        selected_role = request.POST.get("role", "")
        if selected_role not in role_values:
            errors.append("Select a valid role.")
        else:
            for module_key, _ in API_MODULE_CHOICES:
                permission, _ = RoleModulePermission.objects.get_or_create(
                    role=selected_role,
                    module=module_key,
                )
                for action in ("read", "create", "edit", "delete"):
                    setattr(
                        permission,
                        f"can_{action}",
                        request.POST.get(f"{module_key}_can_{action}") == "on",
                    )
                permission.save(
                    update_fields=[
                        "can_read",
                        "can_create",
                        "can_edit",
                        "can_delete",
                    ]
                )

            messages.success(request, "Role permissions were updated.")
            return redirect(
                f"{reverse('admin_web:role_permissions')}?role={selected_role}"
            )

    permissions_by_module = {
        permission.module: permission
        for permission in RoleModulePermission.objects.filter(role=selected_role)
    }
    modules = [
        {
            "key": module_key,
            "label": label,
            "permission": permissions_by_module.get(module_key),
        }
        for module_key, label in API_MODULE_CHOICES
    ]

    return render(
        request,
        "admin_web/role_permissions.html",
        {
            "roles": User.Role.choices,
            "selected_role": selected_role,
            "modules": modules,
            "errors": errors,
        },
    )
