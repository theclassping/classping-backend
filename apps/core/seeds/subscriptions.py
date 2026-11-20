"""
Demo subscriptions: one branch per status, dates relative to today.

    Main Campus   active, Starter + Storage +10 GB, 2 seats left (custom student limit)
    North Campus  trialing, ends in 5 days, open first invoice, custom 100 GB (pilot)
    East Campus   past due 3 days (4 grace days left), open renewal invoice
    West Campus   expired 10 days ago (Growth): read-only

Run again to reset the four branches to these states. No emails are sent.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.branch_subscriptions.catalog import CATALOG
from apps.branch_subscriptions.usage import active_students
from apps.locations.models import Location
from apps.schools.models import Branch, School
from apps.staffs.models import Staff
from apps.users.models import User
from plan_subscriptions import catalog, entitlements, notifications_disabled, services
from plan_subscriptions.models import (
    AddOn,
    Feature,
    FeatureOverride,
    Plan,
    Subscription,
    SubscriptionAddOn,
    SubscriptionEvent,
    SubscriptionInvoice,
)
from plan_subscriptions.money import price_period_end

DEMO_PASSWORD = "password123"  # same as the other seed users
EXTRA_BRANCHES = [
    {"name": "East Campus", "code": "EAST", "email": "east@classping.test", "phone": "0221234569",
     "address": "Jl. Timur No. 3", "officer": "east.officer@classping.test"},
    {"name": "West Campus", "code": "WEST", "email": "west@classping.test", "phone": "0221234570",
     "address": "Jl. Barat No. 4", "officer": "west.officer@classping.test"},
]


def _ensure_extra_branches():
    school = School.objects.get(register_number="CP-2026-001")
    location = Location.objects.get(code="3273060001")
    for data in EXTRA_BRANCHES:
        branch, _ = Branch.objects.get_or_create(
            school=school, code=data["code"],
            defaults={"name": data["name"], "email": data["email"], "phone": data["phone"],
                      "address": data["address"], "location": location},
        )
        user, created = User.objects.get_or_create(
            email=data["officer"],
            defaults={"first_name": data["name"].split()[0], "last_name": "Officer", "role": User.Role.STAFF},
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        Staff.objects.get_or_create(
            user=user,
            defaults={"staff_type": Staff.StaffType.OFFICER, "branch": branch, "first_name": user.first_name,
                      "last_name": user.last_name, "email": user.email, "phone": data["phone"],
                      "hire_date": date(2026, 1, 1), "qualification": "Bachelor of Administration"},
        )


def _reset(branch, plan_code, now, **fields):
    """Fresh subscription for ``branch`` with the given fields; old demo rows removed."""
    plan = Plan.objects.get(code=plan_code)
    price = plan.current_price()
    if Subscription.objects.filter(subscriber=branch).exists():
        _wipe(branch)
    sub = Subscription.objects.create(subscriber=branch, plan=plan, price=price, **fields)
    FeatureOverride.objects.filter(subscriber=branch).delete()
    return sub


def _wipe(branch):
    from apps.branch_subscriptions.models import SubscriptionPayment

    SubscriptionPayment.objects.filter(branch=branch).delete()
    sub = Subscription.objects.get(subscriber=branch)
    SubscriptionInvoice.objects.filter(subscription=sub).delete()
    SubscriptionAddOn.objects.filter(subscription=sub).delete()
    SubscriptionEvent.objects.filter(subscription=sub).delete()
    sub.delete()


def _paid_period(sub, start, kind="renewal"):
    end = price_period_end(start, sub.price)
    invoice = services._create_invoice(
        sub, kind, services._period_lines(sub, sub.price, start, end), start,
        price=sub.price, period_start=start, period_end=end,
    )
    invoice.status, invoice.paid_at, invoice.paid_ref = "paid", start - timedelta(days=2), f"SUB-DEMO-{invoice.pk}"
    invoice.save()
    return invoice


def seed_subscriptions():
    with notifications_disabled(), transaction.atomic():
        catalog.load_catalog(CATALOG)
        _ensure_extra_branches()
        now = timezone.now()
        storage = Feature.objects.get(code="storage_bytes")
        students = Feature.objects.get(code="max_students")
        addon = AddOn.objects.get(code="storage_10gb")
        result = {}

        # Main Campus: active, two paid months, storage add-on, 2 seats left.
        main = Branch.objects.get(name="Main Campus")
        start = now - timedelta(days=10)
        sub = _reset(main, "starter", now, status="active", trial_start=start - timedelta(days=240),
                     trial_end=start - timedelta(days=60))
        _paid_period(sub, start - timedelta(days=60), kind="first")
        _paid_period(sub, start - timedelta(days=30))
        current = _paid_period(sub, start)
        sub.current_period_start, sub.current_period_end = current.period_start, current.period_end
        sub.paid_through = current.period_end
        sub.save()
        purchase = SubscriptionAddOn.objects.create(
            subscription=sub, addon=addon, quantity=1, unit_price=addon.price,
            status="active", started_at=now - timedelta(days=5),
        )
        addon_invoice = services._create_invoice(
            sub, "addon", [services._line(f"{addon.name} (prorated)", 1, addon.price, Decimal("40000"), "addon")],
            now, purchase=purchase, start="now", period_start=now - timedelta(days=5), period_end=sub.current_period_end,
        )
        SubscriptionInvoice.objects.filter(pk=addon_invoice.pk).update(status="paid", paid_at=now - timedelta(days=5),
                                                                       paid_ref="SUB-DEMO-ADDON")
        FeatureOverride.objects.create(subscriber=main, feature=students, value=active_students(main.pk) + 2,
                                       reason="Demo: 2 seats left to test STUDENT_LIMIT_REACHED")
        result["Main Campus"] = "active"

        # North Campus: trial ends in 5 days, first invoice open, pilot storage.
        north = Branch.objects.get(name="North Campus")
        sub = _reset(north, "starter", now, status="trialing", trial_start=now - timedelta(days=175),
                     trial_end=now + timedelta(days=5))
        end = price_period_end(sub.trial_end, sub.price)
        services._create_invoice(sub, "first", services._period_lines(sub, sub.price, sub.trial_end, end),
                                 sub.trial_end, price=sub.price, period_start=sub.trial_end, period_end=end)
        FeatureOverride.objects.create(subscriber=north, feature=storage, value=100 * 1024 ** 3, reason="Pilot school")
        result["North Campus"] = "trialing"

        # East Campus: period ended 3 days ago, unpaid.
        east = Branch.objects.get(code="EAST")
        ended = now - timedelta(days=3)
        sub = _reset(east, "starter", now, status="past_due", trial_start=ended - timedelta(days=210),
                     trial_end=ended - timedelta(days=30))
        _paid_period(sub, ended - timedelta(days=30), kind="first")
        sub.current_period_start, sub.current_period_end, sub.paid_through = ended - timedelta(days=30), ended, ended
        sub.grace_ends_at = ended + timedelta(days=7)
        sub.save()
        services._create_invoice(sub, "renewal", services._period_lines(sub, sub.price, ended, price_period_end(ended, sub.price)),
                                 ended, price=sub.price, period_start=ended, period_end=price_period_end(ended, sub.price))
        result["East Campus"] = "past_due"

        # West Campus: Growth, expired 10 days ago.
        west = Branch.objects.get(code="WEST")
        ended = now - timedelta(days=17)
        sub = _reset(west, "growth", now, status="expired", trial_start=ended - timedelta(days=210),
                     trial_end=ended - timedelta(days=30), expired_at=now - timedelta(days=10))
        _paid_period(sub, ended - timedelta(days=30), kind="first")
        sub.current_period_start, sub.current_period_end, sub.paid_through = ended - timedelta(days=30), ended, ended
        sub.grace_ends_at = ended + timedelta(days=7)
        sub.save()
        SubscriptionAddOn.objects.create(subscription=sub, addon=addon, quantity=1, unit_price=addon.price,
                                         status="ended", started_at=ended - timedelta(days=20), ends_at=ended)
        services._create_invoice(sub, "renewal", services._period_lines(sub, sub.price, ended, price_period_end(ended, sub.price)),
                                 ended, price=sub.price, period_start=ended, period_end=price_period_end(ended, sub.price))
        result["West Campus"] = "expired"

        for branch in (main, north, east, west):
            services.log_event(Subscription.objects.get(subscriber=branch), "demo_seeded", {"state": result[branch.name]})
            entitlements.invalidate(branch.pk)
        entitlements.invalidate_all()
    return result
