"""
Admin web menus for subscriptions (superadmin only):

    Subscriptions  /admin-web/subscriptions/          who is subscribed (list + detail actions)
    Plans          /admin-web/plans/                  what is sold (plans, features, add-ons tabs)

Pages only call plan_subscriptions services / catalog, so every rule is the
same as in the API.
"""
from decimal import Decimal, InvalidOperation

from django.db.models import Prefetch

from ..views_common import *
from apps.branch_subscriptions.access import branch_label
from apps.branch_subscriptions.models import SubscriptionPayment
from apps.branch_subscriptions.usage import usage_of
from plan_subscriptions import catalog, entitlements, services
from plan_subscriptions.exceptions import SubscriptionError
from plan_subscriptions.models import (
    AddOn,
    AddOnFeature,
    Feature,
    FeatureOverride,
    Plan,
    PlanFeature,
    PlanPrice,
    Subscription,
    SubscriptionInvoice,
)
from plan_subscriptions.status import access_until, effective_status

GB = 1024 ** 3


# --- value helpers: bytes are edited as GB ---------------------------------

def display_value(feature, value):
    if value is None:
        return "Unlimited"
    if feature.kind == Feature.Kind.BOOLEAN:
        return "Yes" if value else "No"
    if feature.unit == "bytes":
        gb = value / GB
        return f"{gb:g} GB"
    return f"{value:,}".replace(",", ".") + (f" {feature.unit}" if feature.unit else "")


def input_value(feature, value):
    """Value as shown in a form field."""
    if value is None:
        return ""
    if feature.kind == Feature.Kind.BOOLEAN:
        return "on" if value else "off"
    if feature.unit == "bytes":
        return f"{value / GB:g}"
    return str(value)


def parse_value(feature, raw, unlimited=False):
    """Form value -> stored value. Raises ValueError with a message."""
    if feature.kind == Feature.Kind.BOOLEAN:
        return raw == "on"
    if unlimited:
        return None
    raw = (raw or "").strip().replace(",", ".")
    try:
        number = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{feature.name}: enter a number.")
    if number < 0:
        raise ValueError(f"{feature.name}: cannot be negative.")
    if feature.unit == "bytes":
        return int(number * GB)
    if number != number.to_integral_value():
        raise ValueError(f"{feature.name}: enter a whole number.")
    return int(number)


def _rupiah(value):
    return "Rp " + f"{int(value or 0):,}".replace(",", ".")


# --- Subscriptions menu ------------------------------------------------------

@platform_admin_required
def subscription_list(request):
    now = timezone.now()
    subs = Subscription.objects.select_related("subscriber__school", "plan", "price").order_by(
        "subscriber__school__name", "subscriber__name",
    )
    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "")
    plan_filter = request.GET.get("plan", "")
    if search:
        subs = subs.filter(Q(subscriber__name__icontains=search) | Q(subscriber__school__name__icontains=search))
    if plan_filter:
        subs = subs.filter(plan__code=plan_filter)
    rows = []
    for sub in subs:
        status = effective_status(sub, now)
        if status_filter and status != status_filter:
            continue
        rows.append(sub)
    page_obj = paginate_admin(rows, request)
    for sub in page_obj.object_list:
        sub.effective = effective_status(sub, now)
        sub.until = access_until(sub)
        ent = entitlements.summary(sub.subscriber)["features"]
        used = usage_of(sub.subscriber)
        sub.students = (used["max_students"], ent.get("max_students", {}).get("value"))
        sub.storage_used = used["storage_bytes"]
        sub.storage_limit = ent.get("storage_bytes", {}).get("value")
        sub.open_invoice = sub.invoices.filter(status=SubscriptionInvoice.Status.OPEN).order_by("due_at").first()
    return render(request, "admin_web/subscriptions/list.html", {
        "page_obj": page_obj,
        "statuses": Subscription.Status.choices,
        "plans": Plan.objects.all(),
        "status_filter": status_filter,
        "plan_filter": plan_filter,
        "search": search,
        "without_subscription": Branch.objects.filter(plan_subscription__isnull=True).count(),
    })


@platform_admin_required
def subscription_detail(request, pk):
    sub = get_object_or_404(
        Subscription.objects.select_related("subscriber__school", "plan", "price", "pending_price__plan"), pk=pk,
    )
    branch = sub.subscriber
    now = timezone.now()
    if request.method == "POST":
        return _subscription_action(request, sub)
    summary = entitlements.summary(branch)
    used = usage_of(branch)
    features = []
    for feature in Feature.objects.filter(is_active=True):
        entry = summary["features"].get(feature.code, {})
        features.append({
            "feature": feature,
            "state": entry.get("state"),
            "value": display_value(feature, entry.get("value")) if entry.get("state") != "off" else "—",
            "used": display_value(feature, used[feature.code]) if feature.code in used else "",
        })
    return render(request, "admin_web/subscriptions/detail.html", {
        "sub": sub,
        "branch": branch,
        "label": branch_label(branch),
        "status": effective_status(sub, now),
        "until": access_until(sub),
        "features": features,
        "addons": sub.addons.select_related("addon").order_by("-created_at"),
        "overrides": FeatureOverride.objects.filter(subscriber_id=branch.pk).select_related("feature"),
        "invoices": sub.invoices.select_related("price__plan").order_by("-created_at"),
        "payments": SubscriptionPayment.objects.filter(branch=branch).select_related("invoice", "staff")[:30],
        "events": sub.events.select_related("actor")[:50],
        "prices": PlanPrice.objects.filter(is_active=True).select_related("plan").order_by("plan__sort_order"),
        "all_features": Feature.objects.filter(is_active=True),
    })


def _subscription_action(request, sub):
    action = request.POST.get("action", "")
    user = request.user
    try:
        if action == "extend_trial":
            days = int(request.POST.get("days") or 0)
            if days <= 0:
                raise ValueError("Enter a number of days.")
            services.extend_trial(sub, days, actor=user)
            messages.success(request, f"Trial extended by {days} days.")
        elif action == "set_plan":
            price = get_object_or_404(PlanPrice, pk=request.POST.get("price_id"))
            services.set_plan_without_charge(sub, price, actor=user)
            messages.success(request, f"Tier changed to {price.plan.name} (no charge).")
        elif action == "set_override":
            feature = get_object_or_404(Feature, pk=request.POST.get("feature_id"))
            value = parse_value(feature, request.POST.get("value"), request.POST.get("unlimited") == "on")
            services.set_override(sub.subscriber, feature, value, request.POST.get("reason", "").strip(), actor=user)
            messages.success(request, f"Custom {feature.name} set to {display_value(feature, value)}.")
        elif action == "remove_override":
            override = get_object_or_404(FeatureOverride, pk=request.POST.get("override_id"), subscriber_id=sub.subscriber_id)
            services.remove_override(override, actor=user)
            messages.success(request, "Custom value removed.")
        elif action == "mark_paid":
            invoice = get_object_or_404(SubscriptionInvoice, pk=request.POST.get("invoice_id"), subscription=sub)
            if invoice.status != SubscriptionInvoice.Status.OPEN:
                raise ValueError("Only an open invoice can be marked paid.")
            reference = request.POST.get("reference", "").strip()
            if not reference:
                raise ValueError("Enter the bank transfer reference.")
            services.mark_invoice_paid(invoice, paid_ref=f"manual: {reference}", actor=user,
                                       payment={"payment_method": "Transfer bank", "amount": invoice.total})
            messages.success(request, f"{invoice.number} marked paid.")
        elif action == "void_invoice":
            invoice = get_object_or_404(SubscriptionInvoice, pk=request.POST.get("invoice_id"), subscription=sub)
            services.void_invoice(invoice, actor=user)
            messages.success(request, f"{invoice.number} voided.")
        elif action == "cancel":
            immediately = request.POST.get("immediately") == "on"
            services.cancel(sub, immediately=immediately, actor=user)
            messages.success(request, "Subscription canceled" + (" now." if immediately else " at period end."))
        elif action == "resume":
            services.resume(sub, actor=user)
            messages.success(request, "Cancellation undone.")
        else:
            messages.error(request, "Unknown action.")
    except (ValueError, SubscriptionError) as error:
        messages.error(request, getattr(error, "message", None) or str(error))
    return redirect("admin_web:subscription_detail", sub.pk)


# --- Plans menu: plans tab ---------------------------------------------------

@platform_admin_required
def plan_list(request):
    features = list(Feature.objects.filter(is_active=True))
    plans = Plan.objects.prefetch_related(
        Prefetch("plan_features", queryset=PlanFeature.objects.select_related("feature")),
    ).order_by("sort_order", "code")
    rows = []
    for plan in plans:
        values = {pf.feature_id: pf.value for pf in plan.plan_features.all()}
        price = plan.current_price()
        rows.append({
            "plan": plan,
            "price": _rupiah(price.amount) if price else "—",
            "values": [display_value(f, values[f.pk]) if f.pk in values else "—" for f in features],
            "branches": catalog.subscribers_on_plan(plan).count(),
        })
    return render(request, "admin_web/plans/plans.html", {"rows": rows, "features": features, "tab": "plans"})


@platform_admin_required
def plan_form(request, pk=None):
    plan = get_object_or_404(Plan, pk=pk) if pk else None
    features = list(Feature.objects.filter(is_active=True))
    current = {pf.feature_id: pf.value for pf in plan.plan_features.all()} if plan else {}
    price = plan.current_price() if plan else None
    errors = []
    data = request.POST if request.method == "POST" else None
    if request.method == "POST":
        code = data.get("code", "").strip()
        name = data.get("name", "").strip()
        amount_raw = data.get("price", "").strip().replace(".", "").replace(",", "")
        if not plan and not code:
            errors.append("Code is required.")
        if not plan and code and Plan.objects.filter(code=code).exists():
            errors.append("This code is already used.")
        if not name:
            errors.append("Name is required.")
        try:
            amount = Decimal(amount_raw)
            if amount < 0:
                raise InvalidOperation
        except InvalidOperation:
            errors.append("Price must be a number (rupiah, no decimals).")
            amount = None
        values = {}
        for feature in features:
            mode = data.get(f"f_{feature.pk}_mode", "")  # "" = not included
            if not mode:
                continue
            try:
                if feature.kind == Feature.Kind.BOOLEAN:
                    values[feature] = mode == "on"
                else:
                    values[feature] = parse_value(feature, data.get(f"f_{feature.pk}"), mode == "unlimited")
            except ValueError as error:
                errors.append(str(error))
        trial_raw = data.get("trial_days", "").strip()
        if trial_raw and not trial_raw.isdigit():
            errors.append("Trial days must be a whole number or empty.")
        if not errors:
            with transaction.atomic():
                fields = {
                    "name": name,
                    "description": data.get("description", "").strip(),
                    "sort_order": int(data.get("sort_order") or 0),
                    "is_public": data.get("is_public") == "on",
                    "is_active": data.get("is_active") == "on",
                    "trial_days": int(trial_raw) if trial_raw else None,
                }
                if plan is None:
                    plan = Plan.objects.create(code=code, **fields)
                    catalog.log_change("plan", plan, "created", {"code": code}, request.user)
                else:
                    before = {k: getattr(plan, k) for k in fields}
                    for key, value in fields.items():
                        setattr(plan, key, value)
                    plan.save()
                    changed = {k: [before[k], v] for k, v in fields.items() if before[k] != v}
                    if changed:
                        catalog.log_change("plan", plan, "edited", {k: [str(a), str(b)] for k, (a, b) in changed.items()}, request.user)
                catalog.set_plan_price(plan, amount, actor=request.user,
                                       apply_to_existing=data.get("apply_to_existing") == "on")
                for feature in features:
                    if feature in values:
                        catalog.set_plan_feature(plan, feature, values[feature], actor=request.user)
                    elif feature.pk in current:
                        catalog.remove_plan_feature(plan, feature, actor=request.user)
            over = _branches_over_limits(plan)
            messages.success(request, f"Plan {plan.name} saved." + (
                f" {over} branch(es) on this plan are now over a limit: they keep their data, new additions are blocked."
                if over else ""
            ))
            return redirect("admin_web:plan_list")
    feature_rows = []
    for feature in features:
        if data is not None:
            mode = data.get(f"f_{feature.pk}_mode", "")
            value = data.get(f"f_{feature.pk}", "")
        elif feature.pk in current:
            value_ = current[feature.pk]
            if feature.kind == Feature.Kind.BOOLEAN:
                mode, value = ("on" if value_ else "off"), ""
            else:
                mode, value = ("unlimited" if value_ is None else "limit"), input_value(feature, value_)
        else:
            mode, value = "", ""
        feature_rows.append({"feature": feature, "mode": mode, "value": value,
                             "unit": "GB" if feature.unit == "bytes" else feature.unit})
    branches = catalog.subscribers_on_plan(plan).count() if plan else 0
    stay_on_old = (
        Subscription.objects.filter(price__plan=plan).exclude(price=price).count() if plan and price else 0
    )
    return render(request, "admin_web/plans/plan_form.html", {
        "plan": plan, "price": price, "feature_rows": feature_rows, "errors": errors, "data": data,
        "branches": branches, "stay_on_old": stay_on_old, "tab": "plans",
    })


def _branches_over_limits(plan):
    count = 0
    for sub in catalog.subscribers_on_plan(plan).select_related("subscriber"):
        ent = entitlements.summary(sub.subscriber)["features"]
        used = usage_of(sub.subscriber)
        for code, amount in used.items():
            limit = ent.get(code, {}).get("value")
            if limit is not None and ent.get(code, {}).get("state") != "off" and amount > limit:
                count += 1
                break
    return count


# --- Plans menu: features tab --------------------------------------------------

@platform_admin_required
def feature_list(request):
    return render(request, "admin_web/plans/features.html", {
        "features": Feature.objects.all(), "tab": "features",
    })


@platform_admin_required
def feature_form(request, pk=None):
    feature = get_object_or_404(Feature, pk=pk) if pk else None
    errors = []
    data = request.POST if request.method == "POST" else None
    if request.method == "POST":
        name = data.get("name", "").strip()
        on_expiry = data.get("on_expiry", Feature.OnExpiry.LOCK)
        if not name:
            errors.append("Name is required.")
        if on_expiry not in Feature.OnExpiry.values:
            errors.append("Choose what happens after expiry.")
        if feature is None:
            code = data.get("code", "").strip()
            kind = data.get("kind", "")
            if not code or not code.replace("_", "").isalnum() or not code.islower():
                errors.append("Code: lowercase letters, digits and _ only (used in code, cannot change later).")
            elif Feature.objects.filter(code=code).exists():
                errors.append("This code is already used.")
            if kind not in Feature.Kind.values:
                errors.append("Choose a kind.")
        if not errors:
            fields = {
                "name": name, "on_expiry": on_expiry, "unit": data.get("unit", "").strip(),
                "is_active": data.get("is_active") == "on", "sort_order": int(data.get("sort_order") or 0),
            }
            if feature is None:
                feature = Feature.objects.create(code=code, kind=kind, **fields)
                catalog.log_change("feature", feature, "created", {"code": code, "kind": kind}, request.user)
            else:
                before = {k: getattr(feature, k) for k in fields}
                Feature.objects.filter(pk=feature.pk).update(**fields)
                catalog.log_change("feature", feature, "edited",
                                   {k: [str(before[k]), str(v)] for k, v in fields.items() if before[k] != v}, request.user)
            messages.success(request, f"Feature {name} saved.")
            return redirect("admin_web:feature_list")
    return render(request, "admin_web/plans/feature_form.html", {
        "feature": feature, "errors": errors, "data": data, "tab": "features",
        "kinds": Feature.Kind.choices, "on_expiry_choices": Feature.OnExpiry.choices,
    })


# --- Plans menu: add-ons tab ----------------------------------------------------

@platform_admin_required
def addon_list(request):
    rows = []
    for addon in AddOn.objects.prefetch_related("addon_features__feature", "plans"):
        gives = ", ".join(
            ("+" if af.mode == AddOnFeature.Mode.INCREMENT else "") + f"{display_value(af.feature, af.value)} {af.feature.name}"
            for af in addon.addon_features.all()
        )
        rows.append({
            "addon": addon, "price": _rupiah(addon.price), "gives": gives,
            "plans": ", ".join(p.name for p in addon.plans.all()) or "All plans",
            "active": addon.purchases.filter(status__in=("active", "ending")).count(),
        })
    return render(request, "admin_web/plans/addons.html", {"rows": rows, "tab": "addons"})


@platform_admin_required
def addon_form(request, pk=None):
    addon = get_object_or_404(AddOn, pk=pk) if pk else None
    features = list(Feature.objects.filter(is_active=True).exclude(kind=Feature.Kind.METERED))
    current = {af.feature_id: af for af in addon.addon_features.all()} if addon else {}
    errors = []
    data = request.POST if request.method == "POST" else None
    plans = Plan.objects.all()
    if request.method == "POST":
        code = data.get("code", "").strip()
        name = data.get("name", "").strip()
        billing = data.get("billing", AddOn.Billing.RECURRING)
        if addon is None and (not code or AddOn.objects.filter(code=code).exists()):
            errors.append("Code is required and must be unique.")
        if not name:
            errors.append("Name is required.")
        if billing not in AddOn.Billing.values:
            errors.append("Choose recurring or one-time.")
        try:
            price = Decimal(data.get("price", "").strip().replace(".", "").replace(",", ""))
            if price < 0:
                raise InvalidOperation
        except InvalidOperation:
            errors.append("Price must be a number (rupiah, no decimals).")
            price = None
        max_raw = data.get("max_quantity", "").strip()
        if max_raw and not max_raw.isdigit():
            errors.append("Max quantity must be a whole number or empty.")
        gives = {}
        for feature in features:
            mode = data.get(f"f_{feature.pk}_mode", "")
            if not mode:
                continue
            try:
                if feature.kind == Feature.Kind.BOOLEAN:
                    gives[feature] = (True, AddOnFeature.Mode.GRANT)
                else:
                    gives[feature] = (parse_value(feature, data.get(f"f_{feature.pk}")), mode)
            except ValueError as error:
                errors.append(str(error))
        if not gives:
            errors.append("Choose what the add-on gives (at least one feature).")
        if not errors:
            with transaction.atomic():
                fields = {
                    "name": name, "description": data.get("description", "").strip(), "billing": billing,
                    "price": price, "max_quantity": int(max_raw) if max_raw else None,
                    "is_active": data.get("is_active") == "on", "sort_order": int(data.get("sort_order") or 0),
                }
                if addon is None:
                    addon = AddOn.objects.create(code=code, **fields)
                    catalog.log_change("addon", addon, "created", {"code": code}, request.user)
                else:
                    before = {k: getattr(addon, k) for k in fields}
                    for key, value in fields.items():
                        setattr(addon, key, value)
                    addon.save()
                    changes = {k: [str(before[k]), str(v)] for k, v in fields.items() if before[k] != v}
                    if data.get("apply_to_existing") == "on" and before["price"] != price:
                        moved = addon.purchases.filter(status__in=("active", "ending", "pending_payment")).update(unit_price=price)
                        changes["moved_to_new_price"] = moved
                    catalog.log_change("addon", addon, "edited", changes, request.user)
                addon.plans.set(plans.filter(pk__in=data.getlist("plans")))
                for feature in features:
                    if feature in gives:
                        value, mode = gives[feature]
                        AddOnFeature.objects.update_or_create(addon=addon, feature=feature,
                                                              defaults={"value": value, "mode": mode})
                    elif feature.pk in current:
                        current[feature.pk].delete()
                entitlements.invalidate_all()
            messages.success(request, f"Add-on {name} saved.")
            return redirect("admin_web:addon_list")
    feature_rows = []
    for feature in features:
        if data is not None:
            mode, value = data.get(f"f_{feature.pk}_mode", ""), data.get(f"f_{feature.pk}", "")
        elif feature.pk in current:
            mode, value = current[feature.pk].mode, input_value(feature, current[feature.pk].value)
        else:
            mode, value = "", ""
        feature_rows.append({"feature": feature, "mode": mode, "value": value,
                             "unit": "GB" if feature.unit == "bytes" else feature.unit})
    selected_plans = (
        {int(x) for x in data.getlist("plans")} if data is not None
        else {p.pk for p in addon.plans.all()} if addon else set()
    )
    return render(request, "admin_web/plans/addon_form.html", {
        "addon": addon, "errors": errors, "data": data, "feature_rows": feature_rows, "plans": plans,
        "selected_plans": selected_plans, "billing_choices": AddOn.Billing.choices, "tab": "addons",
        "holders": addon.purchases.filter(status__in=("active", "ending")).count() if addon else 0,
    })
