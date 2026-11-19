# django-plan-subscriptions

Reusable subscriptions for Django: plans whose features live in the database,
add-ons, trials, invoices, grace periods and entitlement checks. The package
knows nothing about what a feature means: no students, no storage. Each
project defines its own.

Python 3.9+, Django 4.2+, Django REST framework.

## Install

```bash
pip install -e ./libs/plan_subscriptions
```

```python
INSTALLED_APPS += ["plan_subscriptions"]

PLAN_SUBSCRIPTIONS_SUBSCRIBER_MODEL = "myapp.Organization"   # who subscribes (like AUTH_USER_MODEL)
PLAN_SUBSCRIPTIONS = {
    "SUBSCRIBER_RESOLVER": "myapp.subs.subscriber_from_request",  # request -> subscriber
    "API_PERMISSION_CLASSES": ["myapp.subs.IsOrgAdmin"],
    "BILLING_BACKEND": "myapp.subs.StripeBilling",                # or the built-in ManualBilling
    "NOTIFIER": "myapp.subs.EmailNotifier",                       # or NullNotifier
    "USAGE_PROVIDER": "myapp.subs.usage_of",                      # subscriber -> {code: used}
    "CURRENCY": "IDR", "TAX_RATE": "0.11", "DEFAULT_TRIAL_DAYS": 30, "TRIAL_PLAN": "basic",
}

urlpatterns += [path("api/subscription/", include("plan_subscriptions.urls"))]
```

Run `python manage.py migrate`, then load your catalog, for example in a data migration:

```python
from plan_subscriptions.catalog import load_catalog

load_catalog({
    "features": [{"code": "max_doctors", "name": "Doctors", "kind": "limit", "on_expiry": "lock"}],
    "plans": [{"code": "basic", "name": "Basic", "prices": [{"interval": "month", "amount": "99000"}],
               "features": {"max_doctors": 5}}],
    "addons": [{"code": "doctors_5", "name": "+5 doctors", "billing": "recurring", "price": "25000",
                "features": [{"feature": "max_doctors", "value": 5, "mode": "increment"}]}],
})
```

`load_catalog` only creates what is missing, so admins can edit prices and limits later.

## Check before acting

```python
from plan_subscriptions import entitlements

entitlements.has(org, "whatsapp_reminders")                        # on / off
entitlements.check_limit(org, "max_doctors", used=count, adding=1)  # raises FeatureLocked / LimitReached
entitlements.limit(org, "max_doctors")                              # None = unlimited
```

The status is worked out from the current time on every check, so read-only
starts exactly when the grace period ends, even if the scheduler is late.

## Lifecycle

`plan_subscriptions.services`: `start_trial`, `subscribe` (after the trial or
"now"), `change_plan` (prorated upgrade, downgrade at period end), `buy_addon`,
`remove_addon`, `cancel`, `mark_invoice_paid` (call it from your payment
webhook), `void_invoice`, `extend_trial`, `set_override`.

Run the scheduled jobs hourly: `services.run_all()`, or
`python manage.py plan_subscriptions_run`.

## Host interfaces

* `billing.BillingBackend`: `quote`, `quote_amount`, `start_payment`, `get_payment`, `cancel_payment`, `list_payments`, `invoice_voided`.
* `notify.Notifier.send(event, subscription, context)`, with events `trial_started`, `trial_ending`,
  `invoice_issued`, `invoice_reminder`, `payment_overdue`, `expired`, `payment_received`.
  Use `notify.notifications_disabled()` while seeding.
