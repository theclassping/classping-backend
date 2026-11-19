# Proposal: Subscription & Plan Module — Draft v3 (implementation plan)

Status: Draft v3 · 19 Nov 2026 · Not yet implemented · Waiting for approval before build

## Changes from Draft v2

| # | Topic | Decision |
|---|---|---|
| 1 | Payment gateway after expiry | Parents get a warning and **cannot pay online**. Same `GATEWAY_DISABLED` reason the app already shows when the gateway is off. |
| 2 | Gateway fee on subscription invoices | **The branch pays the fee on top** (gross-up), the same as parents. It reuses `PaymentAggregator.calculate_transaction_fee`. |
| 3 | Trial | Only **branches created after launch** get a trial. An email goes out when the trial starts, with its end date. Reminders to subscribe go out before it ends. |
| 4 | Grace period | **7 days** past due before read-only. |
| 5 | Who sees and pays | **All staff of the branch** (principal, teacher, officer). Every email goes to the branch email and all active staff, so they can remind each other. |

---

## 1. Summary

| # | Topic | Decision |
|---|---|---|
| 1 | Package | Reusable Django app `libs/plan_subscriptions` (pip name `django-plan-subscriptions`, import `plan_subscriptions`). It has no Classping imports. |
| 2 | Classping wiring | New app `apps/branch_subscriptions`. It holds the subscriber (Branch), payment through `PaymentAggregator`, Mailjet emails, staff permissions and Celery beat. |
| 3 | Subscriber | `Branch` (setting). Another project sets its own model. |
| 4 | Features | Rows in the database, editable in Django admin. The package has **no built-in features**: no students, no storage. Classping defines `max_students` (limit), `storage_bytes` (limit) and `payment_gateway` (on/off). |
| 5 | Pricing | **Tiers** per branch, monthly, excluding PPN 11%: Starter Rp 199.000 (100 students, 50 GB), Growth Rp 449.000 (300 students, 75 GB), Pro Rp 699.000 (500 students, 100 GB). Every tier has the same features; only the limits differ. The fee is grossed up on top at checkout. |
| 6 | Add-ons | Recurring or one-time. Only on a trialing or active subscription. |
| 7 | Trial | 180 days (`DEFAULT_TRIAL_DAYS`). **Always on Starter limits** (100 students, 50 GB), whatever the branch size (`TRIAL_PLAN = "starter"`). At the end of the trial the branch picks the tier that fits its real student count. No free plan. |
| 8 | Expiry | Paid features become **read-only**: images still show but nothing new can be uploaded, no new students can be added or re-activated, and parents cannot pay online. Logins, users, classes, scores and existing students keep working. |
| 9 | Limits | Hard block: storage at upload time, students when a student is added or re-activated. |
| 10 | Management | **Admin web, two menus** (§7a): **Subscriptions** (list of branch subscriptions) and **Plans** (plans, features, add-ons). Django admin stays as a fallback and for apps without admin web. |

### What "Classping wiring" means

The module is split in two, the same way the payment aggregator already is:

| | Payment aggregator (exists today) | Subscriptions (this proposal) |
|---|---|---|
| **Generic package**: works in any project, knows nothing about Classping | `libs/payment_aggregator`: DANA/DOKU clients, fee formula, signing | `libs/plan_subscriptions`: plans, features, add-ons, subscriptions, invoices, entitlements, lifecycle, Django admin, API views |
| **Classping wiring**: the small app that plugs Classping's own pieces into the package | `apps/payment_aggregator`: Classping's contract rates, env key names, shared instance | `apps/branch_subscriptions`: see below |

The package leaves open questions that only the host project can answer. The wiring answers them for Classping:

| Package asks | Classping wiring answers |
|---|---|
| Who subscribes? (`SUBSCRIBER_MODEL`) | `schools.Branch` |
| Which subscriber is this API request for? (`SUBSCRIBER_RESOLVER`) | `request.user.staff.branch` |
| Who may see and pay? (`API_PERMISSION_CLASSES`) | Any active staff of that branch |
| How is an invoice paid? (`BILLING_BACKEND`) | `PaymentAggregator` (DANA), with the `SubscriptionPayment` table and `SUB-` webhook routing |
| How are people notified? (`NOTIFIER`) | Mailjet to the branch email and every active staff member |
| When does a trial start? | `post_save` on `Branch` |
| Who runs the daily jobs? | Celery beat entries |
| Which features exist? | Catalog seed: `max_students`, `storage_bytes`, `payment_gateway` and the Starter / Growth / Pro tiers |
| How much of a limit is used? | Classping counts it: active students of the branch, stored bytes of the branch |
| Where are features enforced? | `apps/students` and admin web (add / import / re-activate student), `apps/uploads` (presign), `apps/payment_gateway` (online payment) call `entitlements` |

Another Django project installs the same package and writes **its own** wiring: for example `Organization` as subscriber, Stripe or Midtrans as billing, SendGrid as notifier. The package code doesn't change.

**The package never knows what a feature means.** It only stores a code, a kind (on/off, limit, metered) and each plan's value. Some examples of how other apps would use the same package:

| App | Subscriber | Features in its own catalog | Its tiers |
|---|---|---|---|
| Classping | Branch | `max_students`, `storage_bytes`, `payment_gateway` | Starter / Growth / Pro by students and GB |
| A clinic app | Clinic | `max_doctors`, `whatsapp_reminders` (on/off), `sms_credits` (metered) | by doctors |
| A POS app | Store | `max_outlets`, `max_products`, `loyalty_program` (on/off) | by outlets |

Each app counts its own usage and calls `entitlements.check_limit(subscriber, "max_doctors", used=..., adding=1)`. The package compares that number with the limit and doesn't care what it counts.

---

## 2. Tables — before

Today, paid features are two columns on `branches`. They are set by hand in admin web and nobody is billed for them.

**`school_branches`** (existing, relevant columns only)

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `school_id` | FK → `schools` | |
| `email` | varchar | |
| `is_payment_gateway_enabled` | bool | Admin web toggle. **Removed** after one release. |
| `storage_capacity_bytes` | bigint, null | Null = `DEFAULT_BRANCH_STORAGE_BYTES`. **Removed** after one release. |

**`storage_addons`** (from `feature/add-on-storage`; **replaced** by the subscription add-on below)

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `branch_id` | FK → `school_branches` | |
| `size_bytes` | bigint | |
| `status` | varchar | pending / approved / rejected / cancelled — superadmin approves by hand |

Unchanged and reused: `staffs` (branch staff, who get the emails and can pay), `media_objects` (storage used per branch), `gateway_payments` (parents' payments), `branch_wallets`.

---

## 3. Tables — after

### Overview

```
features ──< plan_features >── plans ──< plan_prices
    │                            │
    ├──< addon_features >── addons ──< plan_addons >── plans
    │
    ├──< feature_overrides >── school_branches
    └──< usage_records    >── school_branches

school_branches ──1:1── subscriptions ──< subscription_addons >── addons
                              │
                              ├──< subscription_invoices ──< subscription_payments (Classping)
                              └──< subscription_events

──<  means "one to many"
```

### 3a. Package `plan_subscriptions` (generic)

**`features`** — what can be sold. Model `Feature`.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 1 |
| `code` | varchar(50) | unique | Used in code: `entitlements.has(branch, code)` | `storage_bytes` |
| `name` | varchar | | | Storage |
| `kind` | varchar | | `boolean` / `limit` / `metered` | `limit` |
| `unit` | varchar | | | `bytes` |
| `reset_period` | varchar | | Metered only: `none` / `monthly` | `none` |
| `on_expiry` | varchar | | What happens when the subscription expires: `lock` = read-only (nothing new) / `keep` = the last limit still applies | `lock` |
| `is_active` | bool | | | true |

**`plans`** — model `Plan`.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 1 |
| `code` | varchar(50) | unique | | `starter` |
| `name` | varchar | | | Starter |
| `description` | text | | | |
| `trial_days` | int, null | | Null = `DEFAULT_TRIAL_DAYS` (180) | null |
| `is_public` | bool | | Shown on the plans list | true |
| `is_active` | bool | | | true |
| `sort_order` | int | | | 1 |

**`plan_prices`** — model `PlanPrice`. A price change adds a new row; existing subscribers keep theirs.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 1 |
| `plan_id` | bigint | FK → `plans` | | 1 |
| `interval` | varchar | | `month` (`year` later) | `month` |
| `interval_count` | int | | | 1 |
| `amount` | decimal(14,2) | | Excluding PPN | 199000 |
| `currency` | char(3) | | | IDR |
| `is_active` | bool | | Only active prices can be bought | true |

**`plan_features`** — which features a plan includes. Model `PlanFeature`. Editing a value applies to every subscriber of the plan.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 1 |
| `plan_id` | bigint | FK → `plans` | unique with `feature_id` | 1 |
| `feature_id` | bigint | FK → `features` | | 1 (`storage_bytes`) |
| `value` | json | | `true` / a number / `null` = unlimited | 53687091200 (50 GB) |

**`addons`** — model `AddOn`.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 1 |
| `code` | varchar(50) | unique | | `storage_10gb` |
| `name` | varchar | | | Storage +10 GB |
| `billing` | varchar | | `recurring` / `one_time` | `recurring` |
| `price` | decimal(14,2) | | Per unit, monthly if recurring, excl. PPN | 50000 |
| `max_quantity` | int, null | | Null = no limit | 10 |
| `is_active` | bool | | | true |

**`plan_addons`** — which plans an add-on can be bought on. No rows for an add-on = every plan.

| Column | Type | Key |
|---|---|---|
| `plan_id` | bigint | FK → `plans` |
| `addon_id` | bigint | FK → `addons` |

**`addon_features`** — what an add-on gives. Model `AddOnFeature`.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 1 |
| `addon_id` | bigint | FK → `addons` | unique with `feature_id` | 1 |
| `feature_id` | bigint | FK → `features` | | 1 (`storage_bytes`) |
| `value` | json | | | 10737418240 (10 GB) |
| `mode` | varchar | | `grant` = switch on; `increment` = add value × quantity | `increment` |

**`subscriptions`** — one live row per branch. Model `Subscription`.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 7 |
| `subscriber_id` | bigint | FK → `school_branches` | Model set by `SUBSCRIBER_MODEL`. Unique among live rows. | 3 |
| `plan_id` | bigint | FK → `plans` | | 1 |
| `price_id` | bigint | FK → `plan_prices` | The price this branch pays | 1 |
| `status` | varchar | | `trialing` / `active` / `past_due` / `expired` / `canceled` | `active` |
| `trial_start` | datetime, null | | | 2026-06-01 |
| `trial_end` | datetime, null | | | 2026-11-28 |
| `current_period_start` | datetime | | | 2026-12-01 |
| `current_period_end` | datetime | | | 2027-01-01 |
| `cancel_at_period_end` | bool | | | false |
| `canceled_at` | datetime, null | | | |
| `grace_ends_at` | datetime, null | | Set when it becomes `past_due`; read-only starts at this time (§5b) | 2027-01-08 00:00 |
| `expired_at` | datetime, null | | | |
| `metadata` | json | | | {} |

**`subscription_addons`** — add-ons a subscription carries. Model `SubscriptionAddOn`.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 12 |
| `subscription_id` | bigint | FK → `subscriptions` | | 7 |
| `addon_id` | bigint | FK → `addons` | | 1 |
| `quantity` | int | | | 1 |
| `unit_price` | decimal(14,2) | | Price when bought (kept if the add-on price changes) | 50000 |
| `status` | varchar | | `pending_payment` / `active` / `ending` / `ended` / `void` | `active` |
| `started_at` | datetime, null | | Set when paid | 2026-12-12 |
| `ends_at` | datetime, null | | Set when removed | |

**`feature_overrides`** — special deal for one branch. Model `FeatureOverride`.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 1 |
| `subscriber_id` | bigint | FK → `school_branches` | unique with `feature_id` | 3 |
| `feature_id` | bigint | FK → `features` | | 1 |
| `value` | json | | Replaces plan + add-ons | 107374182400 (100 GB) |
| `reason` | varchar | | | Pilot school |
| `expires_at` | datetime, null | | Null = no end | |

**`usage_records`** — metered features only (none at launch). Model `UsageRecord`.

| Column | Type | Key | Notes |
|---|---|---|---|
| `id` | bigint | PK | |
| `subscriber_id` | bigint | FK → `school_branches` | |
| `feature_id` | bigint | FK → `features` | |
| `quantity` | int | | |
| `period_start` | date | | |
| `idempotency_key` | varchar | unique | |

**`subscription_invoices`** — model `SubscriptionInvoice`.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 45 |
| `number` | varchar | unique | | SINV-2026-000045 |
| `subscription_id` | bigint | FK → `subscriptions` | | 7 |
| `kind` | varchar | | `first` / `renewal` / `proration` / `addon` | `addon` |
| `period_start` | datetime | | | 2026-12-12 |
| `period_end` | datetime | | | 2027-01-01 |
| `lines` | json | | `[{description, quantity, unit_price, amount}]` | Storage +10 GB × 1, 12–31 Dec |
| `subtotal` | decimal(14,2) | | Excl. PPN | 30645 |
| `tax` | decimal(14,2) | | PPN 11% | 3371 |
| `total` | decimal(14,2) | | Without gateway fee | 34016 |
| `status` | varchar | | `open` / `paid` / `void` | `paid` |
| `due_at` | datetime | | | 2026-12-19 |
| `paid_at` | datetime, null | | | 2026-12-12 |
| `paid_ref` | varchar | | Payment reference from the host | SUB-20261212-000031 |

**`subscription_events`** — history and duplicate-email guard. Model `SubscriptionEvent`.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | |
| `subscription_id` | bigint | FK → `subscriptions` | | 7 |
| `type` | varchar | | `trial_started`, `reminder_sent`, `activated`, `renewed`, `addon_activated`, `past_due`, `expired`, … | `addon_activated` |
| `dedupe_key` | varchar | unique | The same reminder is never sent twice | `trial_reminder:7:7d` |
| `data` | json | | | |
| `created_at` | datetime | | | |

### 3b. Classping app `branch_subscriptions`

**`subscription_payments`** — one checkout (VA / card) for a subscription invoice. Model `SubscriptionPayment`. A separate table, not `gateway_payments`: that one needs a student and guardian, and paying it credits the branch wallet. Subscription money goes to Classping and **never** touches `branch_wallets`.

| Column | Type | Key | Notes | Example |
|---|---|---|---|---|
| `id` | bigint | PK | | 31 |
| `payment_no` | varchar(50) | unique | Sent to the provider; `SUB-` routes the webhook here | SUB-20261212-000031 |
| `invoice_id` | bigint | FK → `subscription_invoices` | | 45 |
| `branch_id` | bigint | FK → `school_branches` | | 3 |
| `staff_id` | bigint | FK → `staffs` | Who started the payment | 18 |
| `provider` | varchar | | | dana |
| `channel_code` | varchar(50) | | | VIRTUAL_ACCOUNT_BCA |
| `payment_method` | varchar | | | virtual_account |
| `invoice_total` | decimal(14,2) | | `invoice.total` | 34016 |
| `transaction_fee` | decimal(14,2) | | Gross-up, same formula as parents | 2775 |
| `amount` | decimal(14,2) | | Charged | 36791 |
| `status` | varchar | | `pending` / `paid` / `expired` / `cancelled` / `failed` | `paid` |
| `provider_trx_id` | varchar, null | | | |
| `payment_code` | varchar | | VA number | |
| `billing_url` | text | | Payment page | |
| `idempotency_key` | varchar | | | |
| `expires_at` | datetime | | | |
| `paid_at` | datetime, null | | | |
| `provider_response` | json | | | |
| `callback_payload` | json | | | |

### Relationships

| From | To | Type | Rule |
|---|---|---|---|
| `plans` | `plan_prices` | 1 → many | |
| `plans` | `plan_features` | 1 → many | One row per (plan, feature) |
| `addons` | `addon_features` | 1 → many | One row per (add-on, feature) |
| `plans` | `addons` | many ↔ many | Through `plan_addons`; empty = all plans |
| `school_branches` | `subscriptions` | 1 → 1 live | Partial unique index on live statuses |
| `subscriptions` | `subscription_addons` | 1 → many | |
| `subscriptions` | `subscription_invoices` | 1 → many | |
| `subscription_invoices` | `subscription_payments` | 1 → many | A new checkout can follow an expired one |
| `subscriptions` | `subscription_events` | 1 → many | |
| `school_branches` | `feature_overrides` | 1 → many | One per feature |

---

## 4. Entitlements

```
state(feature) =
    off        if the subscriber has no subscription, or the plan/add-ons do not include it
    read_only  if status ∈ {expired, canceled (ended)} and feature.on_expiry = lock
    active     if status ∈ {trialing, active, past_due}
               or (status ∈ {expired, canceled (ended)} and feature.on_expiry = keep)  ← last limit still applies

value(feature) = FeatureOverride.value                        if one exists and has not expired
               = plan value ⊕ Σ add-on values                 otherwise
                 boolean: OR   ·   limit: plan + Σ(increment × qty)   ·   null (unlimited) wins
```

| Feature | `on_expiry` | `active` | After expiry | `off` |
|---|---|---|---|---|
| `max_students` | `lock` | Add / import / re-activate a student while `active students + new ≤ limit` | **Blocked**: existing students stay and keep working; adding, importing or re-activating returns `FEATURE_LOCKED` | — (every tier has it) |
| `storage_bytes` | `lock` | Upload allowed while `used + size ≤ limit` | Images still shown, **uploads blocked** | Uploads blocked |
| `payment_gateway` | `lock` | Parents can pay online | Parents see a warning (`GATEWAY_DISABLED`). Checkouts already started can still be paid. **Wallet and withdrawals stay available.** | Same as after expiry |

**Student limit in Classping.**
- **What counts:** students of the branch with status `active`, compared without case, because the model default is `"ACTIVE"` but the choice is `"active"`. Students who are `inactive`, `out` or `graduated` don't count.
- **Where it's checked:**
  - API student create (`StudentViewSet`);
  - admin web student create and CSV import (`apps/admin_web/views/students.py`, `apps/admin_web/views/schools.py:204`);
  - any change of a student's status to `active` or move to another branch.
- **Import:** the whole file is checked first. If it doesn't fit, nothing is imported, and the error says how many seats are left.
- **Error:** **403** `STUDENT_LIMIT_REACHED` with `limit`, `used` and the tiers that would fit.
- **Concurrency:** the check locks the branch row, the same way the storage check does, so two requests can't both take the last seat.
- **Downgrade with more students than the new limit** (e.g. 250 students → Starter 100): it is allowed. Existing students stay, and new or re-activated students are blocked until the count is under 100.

Public API (`plan_subscriptions.entitlements`):

```python
has(subscriber, code) -> bool                                 # state == active and value truthy
state(subscriber, code) -> "active" | "read_only" | "off"
limit(subscriber, code) -> int | None                         # None = unlimited
check_limit(subscriber, code, used, adding) -> None           # raises FeatureLocked / LimitReached
consume(subscriber, code, quantity, idempotency_key) -> int   # metered; raises LimitReached
summary(subscriber) -> dict                                   # for the API / app
```

Results are cached per subscriber for 5 minutes. The cache is cleared on `entitlements_changed`, which fires on a plan feature edit, add-on change, override or status change.

---

## 5. Lifecycle

Subscription status changes:

| From | To | When | Paid features |
|---|---|---|---|
| — | `trialing` | Branch created | On |
| `trialing` | `active` | First invoice paid, "continue after trial" (period starts at trial end, no trial days lost) | On |
| `trialing` | `active` | First invoice paid, **"start now"** (trial ends early, period starts at payment, the chosen tier's limits apply immediately) | On |
| `trialing` | `past_due` | Trial ended, invoice unpaid | On |
| `active` | `active` | Renewal invoice paid | On |
| `active` | `past_due` | Period ended, invoice unpaid | On |
| `past_due` | `active` | Invoice paid | On |
| `past_due` | `expired` | 7 days (`GRACE_DAYS`) passed, still unpaid | **Read-only** |
| `expired` | `active` | Open invoice paid (new period from payment date) | On |
| `active` | `canceled` | Branch canceled and the period ended | **Read-only** |
| `canceled` | `active` | Branch subscribes again | On |

| Step | What happens | Emails (branch email + all active staff) |
|---|---|---|
| Branch created | `start_trial(branch)` puts it on **Starter** (`TRIAL_PLAN`), `trial_end = now + 180 days` | **trial_started**: Starter limits, end date, tiers to choose from after the trial |
| Staff picks a tier during trial | Two choices, `subscribe(price_id, start="after_trial" \| "now")`:<br>• **Continue after trial**: a `first` invoice whose period starts at `trial_end`. Limits stay at Starter until then.<br>• **Start now**: for a branch that needs more than Starter (e.g. 400 students → Pro). The invoice period starts at payment. When paid, the trial ends early and Pro limits (500 students, 100 GB) apply immediately. The remaining free months are given up, so the app shows that before paying.<br>Picking another tier or choice before paying replaces the open invoice. | — |
| Trial end − 30 / − 7 / − 1 days, unpaid | `issue_due_invoices()` issues the first invoice at −7 days | **trial_ending**: days left, amount, how to pay |
| Trial ends, unpaid | → `past_due`; features still active | **payment_overdue** |
| Period end − 7 days | Renewal invoice issued (plan + recurring add-ons + PPN) | **invoice_issued** |
| Period end − 1 day, unpaid | — | **invoice_reminder** |
| Period end, unpaid | → `past_due` | **payment_overdue** |
| Past due + 7 days | → `expired`; storage, adding students and online payment become read-only (see §5b for how this happens on time) | **subscription_expired**: what stopped, how to re-activate |
| Invoice paid (webhook) | → `active`, period moved forward | **payment_received** |

Reminder days are settings: `TRIAL_REMINDER_DAYS = [30, 7, 1]` and `RENEWAL_REMINDER_DAYS = [7, 1]`.

Plan change and add-ons:

| Action | Behaviour |
|---|---|
| Upgrade | Immediate. A `proration` invoice for the remaining days; the new plan applies once it is paid. |
| Downgrade | At period end. Existing data stays; new uploads are blocked while over the limit. |
| Add recurring add-on | `addon` invoice, prorated for the rest of the period. It starts when paid and then appears on every renewal. |
| Add one-time add-on | `addon` invoice for the full price. It starts when paid. |
| Remove add-on | At period end. |
| Cancel | At period end. In admin web (Subscriptions → detail) an admin can also end it immediately. |

Money: amounts are rounded half-up to whole rupiah. Prorated amount = `price × remaining_seconds / period_seconds`.

### 5b. How read-only starts exactly when the grace period ends

Read-only must start on time even if the Celery job is late or the worker is down. So **enforcement never depends on the job.** Three parts:

**1. Every check compares dates with the current time.**
- When a subscription becomes `past_due`, the column `grace_ends_at` is saved (`period_end` or `trial_end` + `GRACE_DAYS`).
- Every check (upload presign, add student, parent checkout) calls `entitlements`.
- `entitlements` works out the **effective** status from `now`, not only from the stored `status`:

```python
def effective_status(sub, now):
    if sub.status in ("trialing", "active") and now >= sub.period_end_or_trial_end and not sub.has_paid_next_period:
        sub_status = "past_due"            # period ended, nothing paid yet
    else:
        sub_status = sub.status
    if sub_status == "past_due" and now >= sub.grace_ends_at:
        return "expired"                   # read-only from this second
    return sub_status
```

So at 10:00:00 on the 8th day, the next upload or student add is already blocked, whatever the stored row says.

**2. The cache can't outlive a deadline.**
- Entitlements are cached for 5 minutes, **or until the next deadline if that comes sooner**: `ttl = min(300 s, next_boundary − now)`.
- The deadlines are `trial_end`, `period_end` and `grace_ends_at`.
- A cached "active" can never be served after the grace period ends.

**3. The hourly job only records what already happened.**
- `advance_statuses()` (Celery beat, every hour) writes `past_due` / `expired` into the table.
- It also sends the email once (`subscription_events.dedupe_key`) and clears the cache.
- This keeps the admin web list, reports and emails correct. If the job runs 50 minutes late, the email is 50 minutes late, but **access was already read-only on time**.

| Moment | Stored `status` | What checks see | Email |
|---|---|---|---|
| Period ends 1 Jan 00:00, unpaid | `active` → `past_due` at the next hourly run | `past_due` (features on) | payment_overdue |
| 8 Jan 00:00 (`grace_ends_at`) | still `past_due` until the job runs | **`expired` (read-only) immediately** | — |
| 8 Jan 00:05 (job runs) | `expired` | `expired` | subscription_expired (once) |
| 9 Jan, staff pays | `active` (webhook, immediately) | `active`, cache cleared | payment_received |

A VA payment that arrives after expiry still counts. The webhook re-activates the branch with a new period starting from the payment date.

---

### 5a. Storage full in the middle of a period: buying a storage add-on

Example: a branch is on **Starter** (up to 100 students, 50 GB, Rp 199.000/month, period 1–31 Dec). On 12 Dec it reaches 50 GB.

| # | Step | System |
|---|---|---|
| 1 | Staff uploads a photo | Presign: `check_limit` fails → **403** `STORAGE_LIMIT_REACHED` with `used_bytes`, `limit_bytes` and `addons` (the storage add-ons this branch can buy, with prices) so the app can offer "Buy more storage" right away. |
| 2 | Staff picks "Storage +10 GB" | `GET /api/subscription/addons/quote/?addon_code=storage_10gb&quantity=1` → prorated price for 12–31 Dec (Rp 50.000 × 19/31 = Rp 30.645), PPN, and the fee per payment channel. |
| 3 | Staff picks a channel and taps "Pay" | **One request** `POST /api/subscription/addons/ {addon_code, quantity, channel_code}` + `Idempotency-Key` creates the `SubscriptionAddOn` (`pending_payment`), the prorated invoice **and** the checkout, and returns the VA number / payment page URL. The app opens the payment page directly. **No admin approval.** |
| 4 | Webhook: paid | `SubscriptionAddOn` → `active`, entitlement cache cleared. Limit is now **60 GB immediately**. No admin approval. |
| 5 | Staff uploads again | Presign passes. |
| 6 | 1 Jan renewal | One invoice: Starter Rp 199.000 + Storage +10 GB Rp 50.000 + PPN. |

Rules:

| Case | Behaviour |
|---|---|
| When can a branch buy | Any time while `trialing` or `active`. Blocked while `past_due` (pay the overdue invoice first) or `expired` (re-activate first; uploads are read-only anyway). |
| Buying during trial | Allowed. The add-on is charged prorated until `trial_end`, then renews with the first paid period. |
| Buying more than once | Raises `quantity` on the same add-on (up to `max_quantity`). Another prorated invoice is issued for the added quantity. |
| Storage add-on billing | **Recurring monthly.** Storage is an ongoing cost (R2), so storage add-ons are never one-time. One-time add-ons stay available for other services. |
| Payment page expires unpaid | Nothing changes; the limit stays at 50 GB. Staff can pay the same invoice again from `/invoices/{id}/checkout/`. After 7 days unpaid, the invoice and the add-on are voided. |
| Add-on not renewed (renewal unpaid) | Same as the plan: `past_due`, then `expired` → read-only. Files are never deleted. |
| Branch removes the add-on | It ends at period end. If usage is then above the limit (e.g. 55 GB of 50 GB), every existing file stays visible; new uploads are blocked until the branch frees space (storage reset) or buys again. |
| Alternative: upgrade plan | If a bigger plan exists (e.g. Growth: 300 students, 75 GB), the 403 response lists it too. The upgrade follows §5 (prorated, immediate after payment). |

Replaces the `StorageAddOn` request/approve flow on `feature/add-on-storage` (paid outside the system, approved by a superadmin, permanent). Its approved rows are migrated to `FeatureOverride(storage_bytes)` so no branch loses capacity. Its storage enforcement (branch lock at presign) is kept; only `capacity_of()` changes to read `entitlements.limit(branch, "storage_bytes")`.

## 6. Payment flow (reusing the payment aggregator)

```
Staff app                     Classping API                         PaymentAggregator / DANA
   │ GET  /subscription/invoices/7/channels/ ─▶ calculate_transaction_fee(ch, invoice.total) per channel
   │ POST /subscription/invoices/7/checkout/ ─▶ SubscriptionPayment SUB-20261201-000045
   │      {channel_code} + Idempotency-Key      create_billing(reference_no="SUB-…", amount=total+fee) ─▶
   │ ◀── VA number / billing_url
   │                                                         ◀── POST /api/webhooks/payment/ (signed)
   │                          handle_payment_callback: reference "SUB-…" → branch_subscriptions
   │                          SubscriptionPayment → paid → plan_subscriptions.mark_invoice_paid(invoice)
   │                          → subscription active, entitlements cache cleared, email sent
```

Example invoice and checkout:

```
Plan Starter — 1 Dec 2026 – 1 Jan 2027       Rp 199.000
Add-on Storage +10 GB × 1                     Rp  50.000
Subtotal                                      Rp 249.000
PPN 11%                                       Rp  27.390
Invoice total                                 Rp 276.390
Transaction fee (BCA VA, gross-up)            Rp   x.xxx   ← shown at checkout, like parents
Amount to pay                                 Rp 276.390 + fee
```

The VA window, expiry job, sync and cancel use the same rules as parent checkouts. They are reused through shared helpers rather than copied. An invoice stays `open` when a checkout expires, so staff can start a new checkout.

---

## 7. API for staff (all staff roles of the branch)

Base path `/api/subscription/`. The views come from the package; Classping supplies the subscriber resolver (`request.user.staff.branch`) and the permission (active staff of that branch).

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Current subscription: plan, status, trial/period dates, add-ons, entitlement summary, storage used vs limit, open invoice |
| GET | `/plans/` | Public plans with prices and features, and available add-ons |
| POST | `/subscribe/` `{price_id}` | During trial or after expiry: creates the invoice (idempotent: returns the open one) |
| POST | `/change-plan/` `{price_id}` | Upgrade (proration invoice) or schedule a downgrade |
| GET | `/addons/quote/?addon_code=&quantity=` | Prorated price, PPN and fee per channel before paying |
| POST | `/addons/` `{addon_code, quantity, channel_code}` + `Idempotency-Key` | Buys the add-on in one step: creates the add-on, the invoice and the checkout, and returns the payment page / VA. Storage goes up when the webhook confirms payment. |
| DELETE | `/addons/{id}/` | Ends the add-on at period end |
| POST | `/cancel/` | Cancels at period end |
| GET | `/invoices/` · `/invoices/{id}/` | Invoice history and detail with lines |
| GET | `/invoices/{id}/channels/` | Fee quote per channel (gross-up) |
| POST | `/invoices/{id}/checkout/` `{channel_code}` + `Idempotency-Key` | Starts payment; returns VA / billing URL |
| GET | `/payments/{id}/` | Checkout status (polling after payment) |
| POST | `/payments/{id}/cancel/` | Cancels a pending checkout |

Error codes: `SUBSCRIPTION_NOT_FOUND`, `INVOICE_NOT_PAYABLE`, `ADDON_REQUIRES_ACTIVE_SUBSCRIPTION`, `ADDON_QUANTITY_EXCEEDED`, `CHANNEL_NOT_AVAILABLE`, `PROVIDER_UNAVAILABLE`, plus `FEATURE_LOCKED` / `STORAGE_LIMIT_REACHED` on gated endpoints.

---

## 7a. Admin web: two menus

There are two new menu items in admin web (`/admin-web/`), both superadmin-only (`platform_admin_required`), like Online Payments and Wallets.
- **Where the code lives:** the pages are Classping code in `apps/admin_web/views/subscriptions.py` and `apps/admin_web/views/plans.py`, with templates in `templates/admin_web/subscriptions/` and `templates/admin_web/plans/`.
- **No business logic in the pages:** they only call package services (`plan_subscriptions.catalog`, `plan_subscriptions.services`), so every rule is the same as in the API.
- **Django admin** stays as a fallback, and for other apps that have no admin web.

### Menu 1: **Subscriptions** (who is subscribed)

| Page | URL | Shows | Actions |
|---|---|---|---|
| List | `/admin-web/subscriptions/` | One row per branch: school / branch, tier, status, trial or period end, students used / limit, storage used / limit, open invoice amount | Search by school or branch; filter by status (trialing / active / past due / expired / canceled) and tier |
| Detail | `/admin-web/subscriptions/{id}/` | Tier and price, status and dates, add-ons, custom limits, invoices, payments (`SUB-…`), history (status changes, emails sent) | Extend trial, change tier (no charge), set / remove a custom limit, mark an invoice paid (bank transfer), void an invoice, cancel |

### Menu 2: **Plans** (what is sold)

One menu with three tabs:

| Tab | URL | Shows | Actions |
|---|---|---|---|
| **Plans** | `/admin-web/plans/` | One row per tier: name, price/month, every feature's value (e.g. Students 100, Storage 50 GB, Online payment ✔), branches on it, public / active | Create, edit, hide, deactivate |
| **Features** | `/admin-web/plans/features/` | Code, name, kind (on/off, limit, metered), unit, after-expiry rule | Create, rename, change the after-expiry rule. `code` and `kind` are fixed once created, because the code checks them. A new feature appears as a new input on every plan and add-on form. |
| **Add-ons** | `/admin-web/plans/addons/` | Name, price/month, what it adds (e.g. Storage +10 GB), max quantity, branches using it | Create, edit, deactivate |

The plan edit form is built from the Features tab: one input per active feature (a checkbox for on/off, a number for limits, with GB for `bytes`). Adding a feature never needs a code change on this page.

Rules when editing:

| Change | What happens |
|---|---|
| **Plan price** | Saves a **new price row**. New subscribers and anyone changing tier pay the new price. The page shows "N branches stay on Rp X until they change tier". An optional checkbox **"Apply to existing branches from their next renewal"** moves them all on their next invoice. |
| **Plan limit** (students, storage) | Applies to **every branch on that tier immediately**. Before saving, the page shows "This changes the limit for N branches; M of them would be over the new limit (they keep their data, new additions are blocked)". |
| **Add-on price** | New purchases use the new price. Branches that already have it keep their price (`unit_price` is saved per purchase), unless the same "apply from next renewal" checkbox is ticked. |
| **Add-on size** (e.g. 10 GB → 20 GB) | Applies to every branch that has it, immediately. |
| **Deactivate plan / add-on** | It can no longer be bought; current branches keep it until they change. A plan with active branches can't be deleted. |

Every change is logged with the admin user: in `subscription_events` for branches, and in a catalog change log for plans, features and add-ons.

---

## 8. Code — before / after

### 8.1 Settings

**Before** (`config/settings.py`)

```python
DEFAULT_BRANCH_STORAGE_BYTES = ...
```

**After**

```python
INSTALLED_APPS += [
    "plan_subscriptions",
    "apps.branch_subscriptions.apps.BranchSubscriptionsConfig",
]

PLAN_SUBSCRIPTIONS = {
    "SUBSCRIBER_MODEL": "schools.Branch",
    "SUBSCRIBER_RESOLVER": "apps.branch_subscriptions.access.branch_from_request",
    "API_PERMISSION_CLASSES": ["apps.branch_subscriptions.access.IsBranchStaff"],
    "BILLING_BACKEND": "apps.branch_subscriptions.billing.AggregatorBilling",
    "NOTIFIER": "apps.branch_subscriptions.notify.MailjetNotifier",
    "CURRENCY": "IDR",
    "TAX_RATE": "0.11",
    "TAX_LABEL": "PPN 11%",
    "DEFAULT_TRIAL_DAYS": 180,
    "TRIAL_PLAN": "starter",                 # every trial starts on this plan's limits
    "GRACE_DAYS": 7,
    "INVOICE_LEAD_DAYS": 7,
    "TRIAL_REMINDER_DAYS": [30, 7, 1],
    "RENEWAL_REMINDER_DAYS": [7, 1],
    "INVOICE_NUMBER_PREFIX": "SINV",
}

MAILJET_TEMPLATES.update({
    "subscription_trial_started": 8541995,
    "subscription_trial_ending": 8542032,
    "subscription_invoice_issued": 8542034,
    "subscription_invoice_reminder": 8542037,
    "subscription_payment_overdue": 8542044,
    "subscription_expired": 8542045,
    "subscription_payment_received": 8542046,
})
```

### 8.1a Subscription emails (Mailjet)

`MailjetNotifier` (`apps/branch_subscriptions/notify.py`) maps each package event to a template and builds the variables. Each email goes to the branch email and every active staff member of the branch, one message per recipient (the same as the existing `Mailer.send_template`). Every event is sent at most once (`subscription_events.dedupe_key`).

| Event (when) | Template key | ID | Subject | Variables |
|---|---|---|---|---|
| Trial starts (branch created) | `subscription_trial_started` | 8541995 | Masa uji coba ClassPing Anda telah dimulai | `plan_name`, `trial_start_date`, `trial_end_date`, `trial_days` |
| 30 / 7 / 1 days before trial end, nothing paid | `subscription_trial_ending` | 8542032 | Masa uji coba ClassPing berakhir dalam {{var:days_left}} hari | `plan_name`, `trial_end_date`, `days_left` |
| Invoice created (renewal, first, add-on, upgrade) | `subscription_invoice_issued` | 8542034 | Tagihan langganan ClassPing {{var:invoice_number}} | `invoice_number`, `plan_name`, `period_start`, `period_end`, `due_date`, `amount` |
| 1 day before due date, unpaid | `subscription_invoice_reminder` | 8542037 | Pengingat: tagihan {{var:invoice_number}} jatuh tempo {{var:due_date}} | the 6 above + `days_left` |
| Due date passed → `past_due` | `subscription_payment_overdue` | 8542044 | Tagihan {{var:invoice_number}} telah melewati jatuh tempo | `invoice_number`, `due_date`, `days_overdue`, `grace_end_date`, `amount` |
| Grace ended → `expired` | `subscription_expired` | 8542045 | Langganan ClassPing {{var:school_name}} telah berakhir | `plan_name`, `expired_date`, `school_name` (value = branch name) |
| Invoice paid (webhook) | `subscription_payment_received` | 8542046 | Pembayaran {{var:invoice_number}} telah diterima | `invoice_number`, `plan_name`, `period_start`, `period_end`, `paid_at`, `payment_method`, `amount` |

How values are formatted (all sent as ready-to-show strings, so templates need no logic):

| Variable | Format | Example |
|---|---|---|
| `*_date`, `period_start`, `period_end` | Indonesian date, `Asia/Jakarta` | `1 Januari 2027` |
| `paid_at` | Date and time, WIB | `12 Desember 2026, 14:05 WIB` |
| `amount` on invoice emails | Invoice total incl. PPN, **without** gateway fee (the fee depends on the channel chosen at checkout) | `Rp 276.390` |
| `amount` on payment_received | What was actually paid, incl. gateway fee | `Rp 279.165` |
| `days_left`, `days_overdue`, `trial_days` | Whole number | `7` |
| `plan_name` | Tier name; on an add-on-only invoice, the add-on name | `Starter`, `Storage +10 GB` |
| `payment_method` | Channel display name | `BCA Virtual Account` |
| `invoice_number` | | `SINV-2026-000045` |
| `school_name` | Variable name kept as in Mailjet; the **value is the branch** (school + branch name), so a school with two branches can tell them apart. Sent to every template. | `SD Harapan Bangsa – Main Campus` |

During `python manage.py seed` and in tests, no email is sent (`notifications_disabled()`). If Mailjet fails, the error is logged and the status change still happens. The email is retried on the next hourly run because no `dedupe_key` was saved.

### 8.2 Payment gateway check (`apps/payment_gateway/services.py`)

**Before**

```python
    if not invoice.class_student.class_obj.branch.is_payment_gateway_enabled:
        return InvoicePayability(invoice, NotPayableReason.GATEWAY_DISABLED)
```

```python
        is_payment_gateway_enabled=bool(branch and branch.is_payment_gateway_enabled),
```

**After**

```python
from plan_subscriptions import entitlements

    if not entitlements.has(invoice.class_student.class_obj.branch, "payment_gateway"):
        return InvoicePayability(invoice, NotPayableReason.GATEWAY_DISABLED)
```

```python
        is_payment_gateway_enabled=bool(branch and entitlements.has(branch, "payment_gateway")),
```

The API response does not change, so parents see the existing warning. `mark_gateway_payment_paid`, wallet and withdrawal code are not changed. Late payments of checkouts started before expiry still settle.

### 8.3 Webhook routing (`apps/payment_gateway/services.py`)

**Before**

```python
def _apply_payment_callback(provider, billing):
    gateway_payment = GatewayPayment.objects.filter(payment_no=billing.reference_no).first()
    ...
    if gateway_payment is None:
        logger.error("Payment callback for unknown checkout %s / %s", ...)
        return "ignored"
```

**After**

```python
from apps.branch_subscriptions import payments as subscription_payments

def _apply_payment_callback(provider, billing):
    if subscription_payments.owns_reference(billing.reference_no):      # "SUB-" prefix
        return subscription_payments.apply_callback(provider, billing)
    gateway_payment = GatewayPayment.objects.filter(payment_no=billing.reference_no).first()
    ...
```

The provider trx id fallback lookup checks `SubscriptionPayment` too. The settlement reconcile job skips `SUB-` rows because they don't touch the wallet.

### 8.4 Storage (`apps/uploads/usage.py`, `apps/uploads/views.py`)

**Before** — `usage.py`

```python
"""... Capacity is monitored only; nothing here blocks uploads."""

def capacity_of(branch) -> int:
    if branch.storage_capacity_bytes is not None:
        return branch.storage_capacity_bytes
    return settings.DEFAULT_BRANCH_STORAGE_BYTES
```

**After** — `usage.py`

```python
"""... Capacity comes from the branch subscription (feature storage_bytes) and is enforced at presign."""
from plan_subscriptions import entitlements

def capacity_of(branch) -> Optional[int]:
    return entitlements.limit(branch, "storage_bytes")      # None = unlimited

def used_bytes(branch_id) -> int:
    return counted_media().filter(branch_id=branch_id).aggregate(t=Sum("size_bytes"))["t"] or 0
```

**Before** — `PresignUrlView.post`

```python
        location = resolve_upload_location(request.user, data['purpose'], ...)
        ...
        result = MediaService.generate_presign_url(..., size=data['size'], location=location, ...)
```

**After**

```python
        location = resolve_upload_location(request.user, data['purpose'], ...)
        ...
        branch = Branch.objects.get(pk=location.branch_id)
        try:
            entitlements.check_limit(
                branch, "storage_bytes",
                used=used_bytes(location.branch_id), adding=data['size'],
            )
        except entitlements.FeatureLocked:      # expired → read-only
            return Response({'error': 'Subscription expired. Existing images stay visible; '
                             'renew to upload new ones.', 'code': 'FEATURE_LOCKED'},
                            status=status.HTTP_403_FORBIDDEN)
        except entitlements.LimitReached as error:
            return Response({'error': 'Storage is full.', 'code': 'STORAGE_LIMIT_REACHED',
                             'limit_bytes': error.limit, 'used_bytes': error.used},
                            status=status.HTTP_403_FORBIDDEN)
        result = MediaService.generate_presign_url(...)
```

The same check runs in the direct `UploadView`. Download and view URLs are never gated.

### 8.5 Trial on branch create (`apps/branch_subscriptions/signals.py`, new)

**Before** — nothing happens after `Branch.objects.create(...)` in admin web.

**After**

```python
@receiver(post_save, sender=Branch)
def start_branch_trial(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        transaction.on_commit(lambda: services.start_trial(instance))   # sends trial_started
```

The data migration doesn't trigger this, so existing branches get no trial (see §9).

### 8.6 Admin web branch form (`apps/admin_web/views/branches.py`)

**Before** — "Payment gateway" checkbox and "Storage capacity (GB)" field, saved on `Branch`.

**After** — both fields removed. The branch page shows read-only subscription info (tier, status, trial/period end, students used / limit, storage used / limit) with a link to its page in the admin web **Subscriptions** menu (§7a). Per-branch exceptions are set there as an override.

### 8.7 Celery beat (`config/celery.py`)

**After** — added:

```python
    "subscriptions_issue_invoices": {
        "task": "apps.branch_subscriptions.tasks.issue_due_invoices_task",
        "schedule": crontab(hour=1, minute=45),
    },
    "subscriptions_advance_status": {          # trialing/active → past_due → expired
        "task": "apps.branch_subscriptions.tasks.advance_statuses_task",
        "schedule": crontab(minute=5),         # hourly
    },
    "subscriptions_send_reminders": {
        "task": "apps.branch_subscriptions.tasks.send_reminders_task",
        "schedule": crontab(hour=8, minute=15),
    },
```

Each task is a thin wrapper around a plain package function, so a project without Celery can call `manage.py plan_subscriptions_run`.

### 8.8 Package interfaces the host implements

```python
# plan_subscriptions/billing.py
class BillingBackend:
    def quote(self, invoice) -> list[ChannelQuote]: ...
    def start_payment(self, invoice, channel_code, actor, idempotency_key) -> PaymentInstructions: ...
    def get_payment(self, payment_id, subscriber) -> PaymentInstructions: ...
    def cancel_payment(self, payment_id, actor) -> None: ...

class ManualBilling(BillingBackend): ...        # admin clicks "Mark paid" in Django admin

# plan_subscriptions/notify.py
class Notifier:
    def send(self, event: str, subscription, context: dict) -> None: ...

class NullNotifier(Notifier): ...               # default: log only
```

---

## 9. Seed data and migration

There are two kinds of seed data, loaded in different ways:

| Kind | What | Where it runs | How |
|---|---|---|---|
| **Catalog** | Features, plans, prices, add-ons | Every environment, **production included** | Data migration `branch_subscriptions/0002_seed_catalog`, which calls `load_catalog(CATALOG)` |
| **Demo** | Subscriptions in every status, invoices, payments and add-ons for the seed branches | Local / staging only | `python manage.py seed subscriptions` (and part of a full `python manage.py seed`) |

### 9.1 Catalog seed (all environments)

The catalog lives in one Python file, `apps/branch_subscriptions/catalog.py`. The package provides `plan_subscriptions.catalog.load_catalog(data)`, so another project seeds its own catalog the same way.

`load_catalog` only **creates what is missing** (matched by `code`). It never overwrites a value an admin changed in Django admin, so running the migration or the seed again is safe.

**Features**

| code | name | kind | unit | on_expiry |
|---|---|---|---|---|
| `max_students` | Active students | limit | students | `lock` |
| `storage_bytes` | Image storage | limit | bytes | `lock` |
| `payment_gateway` | Online payment for parents | boolean | — | `lock` |

**Plans (tiers)**: monthly, excluding PPN. A 6-month trial comes first (`DEFAULT_TRIAL_DAYS = 180`). Every tier has the same features; only the limits differ.

| code | name | price / month | `max_students` | `storage_bytes` | `payment_gateway` | sort_order |
|---|---|---|---|---|---|---|
| `starter` | Starter | Rp 199.000 | 100 | 50 GB | true | 1 |
| `growth` | Growth | Rp 449.000 | 300 | 75 GB | true | 2 |
| `pro` | Pro | Rp 699.000 | 500 | 100 GB | true | 3 |

A branch with more than 500 students gets a `FeatureOverride(max_students)` set by an admin (custom deal).

**Add-ons**

| code | name | billing | price / unit / month (excl. PPN) | feature | mode | value | max_quantity | Plans |
|---|---|---|---|---|---|---|---|---|
| `storage_10gb` | Storage +10 GB | recurring | Rp 50.000 _(placeholder)_ | `storage_bytes` | increment | 10 GB | 10 | All |

```python
# apps/branch_subscriptions/catalog.py
GB = 1024 ** 3
SAME_FOR_ALL_TIERS = {"payment_gateway": True}

CATALOG = {
    "features": [
        {"code": "max_students", "name": "Active students", "kind": "limit", "unit": "students", "on_expiry": "lock"},
        {"code": "storage_bytes", "name": "Image storage", "kind": "limit", "unit": "bytes", "on_expiry": "lock"},
        {"code": "payment_gateway", "name": "Online payment for parents", "kind": "boolean", "on_expiry": "lock"},
    ],
    "plans": [
        {
            "code": "starter", "name": "Starter", "sort_order": 1,
            "prices": [{"interval": "month", "amount": "199000"}],
            "features": {"max_students": 100, "storage_bytes": 50 * GB, **SAME_FOR_ALL_TIERS},
        },
        {
            "code": "growth", "name": "Growth", "sort_order": 2,
            "prices": [{"interval": "month", "amount": "449000"}],
            "features": {"max_students": 300, "storage_bytes": 75 * GB, **SAME_FOR_ALL_TIERS},
        },
        {
            "code": "pro", "name": "Pro", "sort_order": 3,
            "prices": [{"interval": "month", "amount": "699000"}],
            "features": {"max_students": 500, "storage_bytes": 100 * GB, **SAME_FOR_ALL_TIERS},
        },
    ],
    "addons": [
        {
            "code": "storage_10gb", "name": "Storage +10 GB", "billing": "recurring",
            "price": "50000", "max_quantity": 10,
            "features": [{"feature": "storage_bytes", "value": 10 * GB, "mode": "increment"}],
        },
    ],
}
```

### 9.2 Existing branches at launch (same data migration, production)

| Step | Action |
|---|---|
| 1 | Load the catalog (§9.1). |
| 2 | Existing branches get **the same start as a new branch** (no free access at full size): a 6-month trial on **Starter** limits (100 students, 50 GB), with the trial_started email. A branch with more than 100 active students keeps all of them (nothing is deactivated), but cannot add or re-activate students until it pays for a tier that fits ("start now", e.g. Pro). See open question Q1. |
| 3 | Branches with a custom `storage_capacity_bytes` → `FeatureOverride(storage_bytes)` with that value. |
| 4 | Approved `StorageAddOn` rows (from `feature/add-on-storage`) → added into that branch's `FeatureOverride(storage_bytes)`, so no branch loses capacity. |
| 5 | Next release: drop `Branch.is_payment_gateway_enabled`, `Branch.storage_capacity_bytes` and the `storage_addons` table. |

### 9.3 Demo seed (local / staging)

New file `apps/core/seeds/subscriptions.py` with `seed_subscriptions()`, following the other seed files:
- It runs last in `python manage.py seed`, after `seed_billing`.
- It can run alone: `python manage.py seed subscriptions` (new choice next to `billing` and `demo_student_data`).
- It is idempotent: it uses `get_or_create`, and running it again resets the demo branches to the states below.
- **No emails are sent while seeding.** The seed runs inside `plan_subscriptions.notifications_disabled()`. The `Branch` trial signal also creates trials quietly here, because `seed_branches` runs first.
- Dates are relative to today, so the demo always shows "trial ends in 5 days" and so on.

One branch per status, so every screen and job can be tested. `Main Campus` and `North Campus` already exist. The seed adds `East Campus` and `West Campus`, each with one officer login (`east.officer@classping.test`, `west.officer@classping.test`), using the same test password as the other seed users.

| Branch | Status | Plan | Add-ons | Dates (relative to today) | Invoices | Payments | Tests |
|---|---|---|---|---|---|---|---|
| Main Campus | `active` | Starter | Storage +10 GB × 1 (active) → 60 GB | Period started 10 days ago, ends in 20 days | 2 paid renewals; 1 paid prorated add-on invoice | `SUB-` payments: paid (BCA VA), expired (Mandiri VA) | Normal use, invoice history, buying more storage, upgrade to Growth. A `FeatureOverride(max_students)` = current active students + 2, so adding the 3rd new student shows `STUDENT_LIMIT_REACHED` |
| North Campus | `trialing` | Starter | — | Trial started 175 days ago, **ends in 5 days** | 1 open `first` invoice | — | Trial banner, trial-ending email, paying during the trial |
| East Campus | `past_due` | Starter | — | Period ended 3 days ago (4 grace days left) | 1 open renewal invoice, overdue | 1 pending VA payment | Overdue banner, features still on, paying to re-activate |
| West Campus | `expired` | Growth | Storage +10 GB × 1 (ended) | Expired 10 days ago | 1 open invoice | — | Read-only: images visible, upload → `FEATURE_LOCKED`, parent online payment → `GATEWAY_DISABLED`, withdrawal still works, adding a student → `FEATURE_LOCKED` |

Extra demo rows:
- One `FeatureOverride` on North Campus: `storage_bytes` = 100 GB, reason "Pilot school", so the admin screen shows an override.
- `subscription_events` for each branch, matching its history (trial started, activated, reminder sent, …).

### 9.4 Test factories

The package ships `plan_subscriptions.testing`, like `payment_aggregator.testing`. It has:
- `make_catalog()`, `make_subscription(subscriber, status=..., plan=..., addons=...)` and `make_invoice(...)`;
- `FakeBillingBackend`, which records each call and lets a test mark a payment paid;
- `frozen_clock(...)`, for lifecycle tests.

Classping tests use these instead of the demo seed.

---

## 10. Build order

| # | Step | Tests |
|---|---|---|
| 1 | Package skeleton `libs/plan_subscriptions` (pyproject, src layout, swappable subscriber, models, migrations, Django admin) | Model constraints, admin loads |
| 2 | Entitlement resolver + cache | Plan + add-on + override combinations, read-only state, unlimited |
| 3 | Lifecycle services: trial, subscribe, renew, past_due/expire, change plan, add-ons, cancel, proration, PPN | Clock-driven tests for every transition in §5, idempotent jobs |
| 4 | DRF views + `BillingBackend` / `Notifier` interfaces + `ManualBilling` | API tests with a fake backend |
| 5 | `apps/branch_subscriptions`: `SubscriptionPayment`, `AggregatorBilling`, webhook routing, `MailjetNotifier`, staff access, Celery tasks | Checkout → callback → active; fee gross-up equals parents' formula; wallet untouched |
| 6 | Gate payment gateway, uploads and students (§4, §8.2, §8.4) | Expired branch: parent sees `GATEWAY_DISABLED`, upload blocked, images still served, withdrawal still works, adding a student → `FEATURE_LOCKED`. Active branch at its student limit: API create, admin web create, CSV import and re-activation all return `STUDENT_LIMIT_REACHED`; two requests at once cannot both take the last seat |
| 7 | Catalog file + `load_catalog` + catalog data migration (§9.1) | Run twice → no duplicates, admin edits kept |
| 8 | Existing-branch migration (§9.2), admin web branch form, **admin web Subscriptions and Plans menus** (§7a) | Migration on a copy of current data; price edit keeps old subscribers on old price; limit edit shows affected branches; superadmin-only |
| 9 | Demo seed `seed subscriptions` (§9.3) | Seed twice → same 4 states, no emails sent |
| 10 | `docs/frontend-api-contract.md` additions for §7 | — |

Out of scope (v1): yearly billing (the model is ready for it), coupons, faktur pajak generation, card auto-charge, and frontend screens.

---

## 11. Open questions

1. **Existing branches at launch.** Since free access at full size costs too much, I propose they start like a new branch: a 6-month trial on Starter limits. A branch with 400 students keeps all 400 but can't add more until it pays for Pro ("start now"). The alternative is no trial at all, so they pay for the tier that fits from day one. Which one? Also, should branches with the gateway **off** today get it switched on?
2. **Payment link in emails.** No template has a payment link. Should I send `pay_url` (an app deep link or web page to the invoice)? `school_name` (value = branch name) is sent to every template.
3. **"Start now" tiers.** Can a trial branch "start now" on Starter too (to pay early), or only on Growth and Pro? I propose only Growth and Pro, since paying for Starter early only shortens their free months.
