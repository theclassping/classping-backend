"""
Subscription lifecycle. Every state change goes through here.

    start_trial(subscriber)                    trialing on TRIAL_PLAN
    subscribe(sub, price, start)               invoice for a tier ("period" = after the
                                               trial / current period, "now" = on payment)
    change_plan(sub, price)                    upgrade (prorated invoice) / downgrade at period end
    buy_addon(sub, addon, quantity)            prorated add-on invoice; active once paid
    remove_addon(purchase)                     ends at period end
    cancel(sub, immediately=False)
    mark_invoice_paid(invoice, ref)            called from the host's payment webhook
    void_invoice(invoice)
    issue_due_invoices(now)  advance_statuses(now)  send_reminders(now)   scheduled jobs

Amounts on plans and add-ons exclude tax; invoices add PLAN_SUBSCRIPTIONS["TAX_RATE"].
"""
import logging
import math
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import conf, entitlements, notify
from .exceptions import (
    AddonNotAllowed,
    AddonQuantityExceeded,
    InvalidRequest,
    InvoiceNotPayable,
    PlanChangeNotAllowed,
    SubscriptionNotFound,
)
from .models import (
    AddOn,
    Plan,
    PlanPrice,
    Subscription,
    SubscriptionAddOn,
    SubscriptionEvent,
    SubscriptionInvoice,
)
from .money import as_str, price_period_end, prorate, quantize, tax_of
from .status import ENDED, access_until, effective_price, effective_status, grace_end

logger = logging.getLogger(__name__)

S = Subscription.Status
I = SubscriptionInvoice
A = SubscriptionAddOn.Status
PERIOD_KINDS = (I.Kind.FIRST, I.Kind.RENEWAL)


# --- helpers ---------------------------------------------------------------

def get_subscription(subscriber, lock=False):
    qs = Subscription.objects.select_related("plan", "price__plan", "pending_price__plan")
    if lock:
        qs = qs.select_for_update(of=("self",))
    sub = qs.filter(subscriber_id=getattr(subscriber, "pk", subscriber)).first()
    if sub is None:
        raise SubscriptionNotFound()
    return sub


def _lock(sub):
    return Subscription.objects.select_for_update(of=("self",)).select_related(
        "plan", "price__plan", "pending_price__plan",
    ).get(pk=sub.pk)


def log_event(sub, type_, data=None, actor=None, dedupe_key=None):
    try:
        with transaction.atomic():
            return SubscriptionEvent.objects.create(
                subscription=sub, type=type_, data=data or {}, dedupe_key=dedupe_key,
                actor=actor if getattr(actor, "pk", None) else None,
            )
    except IntegrityError:
        return None  # same dedupe_key already logged


def _changed(sub):
    entitlements.invalidate(sub.subscriber_id)


def _notify_once(sub, event, context, dedupe_key, data=None):
    """Send unless already sent; a failed send is retried on the next run."""
    if SubscriptionEvent.objects.filter(dedupe_key=dedupe_key).exists():
        return False
    if not notify.send(event, sub, context):
        return False
    log_event(sub, f"email:{event}", data or {}, dedupe_key=dedupe_key)
    return True


def _line(description, quantity, unit_price, amount, type_, ref=None):
    return {
        "description": description,
        "quantity": quantity,
        "unit_price": as_str(unit_price),
        "amount": as_str(amount),
        "type": type_,
        "ref": ref,
    }


def _fmt_period(start, end):
    s, e = timezone.localtime(start), timezone.localtime(end)
    return f"{s:%d %b %Y} – {e:%d %b %Y}"


def _create_invoice(sub, kind, lines, due_at, *, price=None, purchase=None, start=I.Start.PERIOD,
                    period_start=None, period_end=None):
    subtotal = quantize(sum((Decimal(line["amount"]) for line in lines), Decimal(0)))
    tax = tax_of(subtotal)
    rate = conf.tax_rate()
    if rate:
        lines = lines + [_line(conf.get("TAX_LABEL"), 1, tax, tax, "tax")]
    invoice = SubscriptionInvoice.objects.create(
        number="TMP-" + uuid.uuid4().hex,
        subscription=sub, kind=kind, price=price, addon_purchase=purchase, start=start,
        period_start=period_start, period_end=period_end, lines=lines,
        subtotal=subtotal, tax=tax, total=subtotal + tax, currency=conf.get("CURRENCY"),
        due_at=due_at,
    )
    year = timezone.localtime(invoice.created_at).year
    invoice.number = "{}-{}-{:06d}".format(conf.get("INVOICE_NUMBER_PREFIX"), year, invoice.pk)
    invoice.save(update_fields=["number"])
    log_event(sub, "invoice_issued", {"invoice": invoice.number, "kind": kind, "total": as_str(invoice.total)})
    transaction.on_commit(lambda: _notify_invoice_issued(invoice.pk))
    return invoice


def _notify_invoice_issued(invoice_id):
    invoice = SubscriptionInvoice.objects.select_related("subscription", "price__plan").get(pk=invoice_id)
    if invoice.status != I.Status.OPEN:
        return
    _notify_once(
        invoice.subscription, "invoice_issued",
        {"invoice": invoice, "plan_name": invoice_plan_name(invoice)},
        f"invoice_issued:{invoice.pk}",
    )


def invoice_plan_name(invoice):
    if invoice.price_id:
        return invoice.price.plan.name
    if invoice.addon_purchase_id:
        return invoice.addon_purchase.addon.name
    return invoice.subscription.plan.name


def _period_lines(sub, price, period_start, period_end):
    lines = [_line(
        f"{price.plan.name} — {_fmt_period(period_start, period_end)}",
        1, price.amount, price.amount, "plan", price.pk,
    )]
    for purchase in _recurring_purchases(sub, period_start):
        amount = purchase.unit_price * purchase.quantity
        lines.append(_line(
            f"{purchase.addon.name} — {_fmt_period(period_start, period_end)}",
            purchase.quantity, purchase.unit_price, amount, "addon", purchase.pk,
        ))
    return lines


def _recurring_purchases(sub, period_start):
    """Recurring add-ons that continue into a period starting at period_start."""
    return [
        p for p in sub.addons.select_related("addon").filter(status=A.ACTIVE)
        if p.addon.billing == AddOn.Billing.RECURRING and (p.ends_at is None or p.ends_at > period_start)
    ]


def _void_open_period_invoices(sub, exclude=None):
    qs = sub.invoices.filter(status=I.Status.OPEN, kind__in=PERIOD_KINDS + (I.Kind.UPGRADE,))
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    for invoice in qs:
        _void(invoice)


def _void(invoice):
    host_cancel = conf.billing_backend()
    invoice.status = I.Status.VOID
    invoice.voided_at = timezone.now()
    invoice.save(update_fields=["status", "voided_at"])
    if invoice.addon_purchase_id:
        SubscriptionAddOn.objects.filter(pk=invoice.addon_purchase_id, status=A.PENDING_PAYMENT).update(status=A.VOID)
    log_event(invoice.subscription, "invoice_voided", {"invoice": invoice.number})
    transaction.on_commit(lambda: _cancel_host_payments(host_cancel, invoice))


def _cancel_host_payments(backend, invoice):
    try:
        backend.invoice_voided(invoice)
    except Exception:
        logger.exception("Billing backend failed to cancel payments of %s", invoice.number)


# --- trial and subscribe ---------------------------------------------------

def trial_plan(plan=None):
    code = conf.get("TRIAL_PLAN")
    if code:
        return Plan.objects.get(code=code)
    if plan is None:
        raise InvalidRequest("No plan given and PLAN_SUBSCRIPTIONS['TRIAL_PLAN'] is not set.")
    return plan


def start_trial(subscriber, plan=None, now=None, actor=None, notify_=True, trial_days=None):
    """Create the subscription in trial. Returns the existing one if there is one."""
    now = now or timezone.now()
    existing = Subscription.objects.filter(subscriber_id=subscriber.pk).first()
    if existing is not None:
        return existing
    plan = trial_plan(plan)
    price = plan.current_price()
    if price is None:
        raise InvalidRequest(f"Plan {plan.code} has no active price.")
    days = trial_days if trial_days is not None else (
        plan.trial_days if plan.trial_days is not None else int(conf.get("DEFAULT_TRIAL_DAYS"))
    )
    with transaction.atomic():
        if days > 0:
            sub = Subscription.objects.create(
                subscriber=subscriber, plan=plan, price=price, status=S.TRIALING,
                trial_start=now, trial_end=now + timedelta(days=days),
            )
            log_event(sub, "trial_started", {"plan": plan.code, "days": days}, actor=actor)
        else:
            # No trial: nothing is covered until the first invoice is paid.
            sub = Subscription.objects.create(
                subscriber=subscriber, plan=plan, price=price, status=S.EXPIRED, expired_at=now,
            )
            log_event(sub, "created_without_trial", {"plan": plan.code}, actor=actor)
    _changed(sub)
    if days > 0 and notify_:
        transaction.on_commit(lambda: _notify_once(
            sub, "trial_started",
            {"plan": plan, "trial_start": sub.trial_start, "trial_end": sub.trial_end, "trial_days": days},
            f"trial_started:{sub.pk}",
        ))
    return sub


def subscribe(sub, price, start=I.Start.PERIOD, actor=None, now=None):
    """
    Invoice for a tier. Replaces any open first / renewal / upgrade invoice.

    trialing  start="period": first invoice, period starts at trial end (limits stay
              on the trial plan until then). start="now": period starts when paid and
              the trial ends early.
    past_due  continues from where access ended (no free days).
    expired / canceled: period starts when paid.
    active    use change_plan.
    """
    now = now or timezone.now()
    if isinstance(price, int):
        price = PlanPrice.objects.select_related("plan").get(pk=price)
    if not price.is_active or not price.plan.is_active:
        raise InvalidRequest("This plan is not available.")
    with transaction.atomic():
        sub = _lock(sub)
        status = effective_status(sub, now)
        if status == S.ACTIVE:
            raise PlanChangeNotAllowed("The subscription is active; change the plan instead.")
        if status == S.TRIALING:
            if start == I.Start.NOW:
                if price.plan_id == sub.plan_id:
                    raise PlanChangeNotAllowed("Starting now is for a bigger plan than the trial plan.")
                kind, period_start = I.Kind.FIRST, now
                due_at = now + timedelta(days=int(conf.get("PURCHASE_INVOICE_DAYS")))
            else:
                start = I.Start.PERIOD
                kind, period_start, due_at = I.Kind.FIRST, sub.trial_end, sub.trial_end
        elif status == S.PAST_DUE:
            start = I.Start.PERIOD
            kind, period_start = I.Kind.RENEWAL, access_until(sub)
            due_at = grace_end(sub)
        else:
            start = I.Start.NOW
            kind, period_start = I.Kind.RENEWAL, now
            due_at = now + timedelta(days=int(conf.get("PURCHASE_INVOICE_DAYS")))
        period_end = price_period_end(period_start, price)
        _void_open_period_invoices(sub)
        invoice = _create_invoice(
            sub, kind, _period_lines(sub, price, period_start, period_end), due_at,
            price=price, start=start, period_start=period_start, period_end=period_end,
        )
        log_event(sub, "plan_chosen", {"plan": price.plan.code, "start": start, "invoice": invoice.number}, actor=actor)
    return invoice


def change_plan(sub, price, actor=None, now=None):
    """Active subscriptions. Upgrade: prorated invoice, new limits once paid. Downgrade: at period end."""
    now = now or timezone.now()
    if isinstance(price, int):
        price = PlanPrice.objects.select_related("plan").get(pk=price)
    with transaction.atomic():
        sub = _lock(sub)
        if effective_status(sub, now) != S.ACTIVE:
            raise PlanChangeNotAllowed("Only an active subscription can change plan.")
        current = effective_price(sub, now)
        if price.pk == current.pk or (price.plan_id == current.plan_id and price.amount == current.amount):
            raise PlanChangeNotAllowed("This is already the current plan.")
        if price.amount > current.amount:
            period_end = sub.current_period_end or access_until(sub)
            period_start = sub.current_period_start or now
            amount = prorate(price.amount - current.amount, now, period_end, period_start, period_end)
            for open_upgrade in sub.invoices.filter(status=I.Status.OPEN, kind=I.Kind.UPGRADE):
                _void(open_upgrade)
            invoice = _create_invoice(
                sub, I.Kind.UPGRADE,
                [_line(f"Upgrade {current.plan.name} → {price.plan.name} — {_fmt_period(now, period_end)}",
                       1, amount, amount, "upgrade", price.pk)],
                now + timedelta(days=int(conf.get("PURCHASE_INVOICE_DAYS"))),
                price=price, start=I.Start.NOW, period_start=now, period_end=period_end,
            )
            log_event(sub, "upgrade_requested", {"to": price.plan.code, "invoice": invoice.number}, actor=actor)
            return invoice
        sub.pending_price = price
        sub.pending_from = sub.current_period_end or access_until(sub)
        sub.save(update_fields=["pending_price", "pending_from", "updated_at"])
        # The next renewal invoice must bill the new price.
        for invoice in sub.invoices.filter(status=I.Status.OPEN, kind__in=PERIOD_KINDS):
            _void(invoice)
        log_event(sub, "downgrade_scheduled", {"to": price.plan.code, "from": sub.pending_from.isoformat()}, actor=actor)
    _changed(sub)
    return None


def cancel(sub, immediately=False, actor=None, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        sub = _lock(sub)
        if immediately:
            sub.status = S.CANCELED
            sub.canceled_at = now
            sub.expired_at = now
            sub.save(update_fields=["status", "canceled_at", "expired_at", "updated_at"])
            for invoice in sub.invoices.filter(status=I.Status.OPEN):
                _void(invoice)
        else:
            sub.cancel_at_period_end = True
            sub.canceled_at = now
            sub.save(update_fields=["cancel_at_period_end", "canceled_at", "updated_at"])
            for invoice in sub.invoices.filter(status=I.Status.OPEN, kind__in=PERIOD_KINDS):
                _void(invoice)
        log_event(sub, "canceled", {"immediately": immediately}, actor=actor)
    _changed(sub)
    return sub


def resume(sub, actor=None):
    """Undo a cancel-at-period-end before the period ends."""
    with transaction.atomic():
        sub = _lock(sub)
        sub.cancel_at_period_end = False
        sub.canceled_at = None
        sub.save(update_fields=["cancel_at_period_end", "canceled_at", "updated_at"])
        log_event(sub, "resumed", actor=actor)
    _changed(sub)
    return sub


# --- add-ons ---------------------------------------------------------------

def addon_quote(sub, addon, quantity, now=None):
    """Price of buying ``quantity`` of ``addon`` now (prorated for recurring add-ons)."""
    now = now or timezone.now()
    status = effective_status(sub, now)
    if status not in (S.TRIALING, S.ACTIVE):
        raise AddonNotAllowed()
    if not addon.is_active or not addon.available_on(sub.plan):
        raise InvalidRequest("This add-on is not available for the current plan.")
    if quantity < 1:
        raise InvalidRequest("quantity must be at least 1.")
    if addon.max_quantity is not None:
        held = sum(
            p.quantity for p in sub.addons.filter(
                addon=addon, status__in=(A.PENDING_PAYMENT, A.ACTIVE),
            )
        )
        if held + quantity > addon.max_quantity:
            raise AddonQuantityExceeded(
                f"At most {addon.max_quantity} of {addon.name}; this subscription has {held}.",
                max_quantity=addon.max_quantity, held=held,
            )
    full = quantize(addon.price * quantity)
    if addon.billing == AddOn.Billing.ONE_TIME:
        period_start, period_end, amount = now, None, full
    else:
        # Charged from now until the current period (or the trial) ends, at the
        # monthly price: 19 of 31 days -> 19/31; 5 months of trial left -> 5x.
        period_end = access_until(sub)
        if status == S.ACTIVE and sub.current_period_end and sub.current_period_end > now:
            period_end = sub.current_period_end
        if period_end is None or period_end <= now:
            raise AddonNotAllowed()
        month_start = _month_before(period_end, sub.price)
        month_seconds = Decimal(str((period_end - month_start).total_seconds()))
        remaining = Decimal(str((period_end - now).total_seconds()))
        amount = quantize(full * remaining / month_seconds)
    subtotal = amount
    tax = tax_of(subtotal)
    return {
        "addon": addon, "quantity": quantity, "unit_price": addon.price, "full_amount": full,
        "period_start": now, "period_end": period_end, "subtotal": subtotal, "tax": tax,
        "total": subtotal + tax,
    }


def _month_before(end, price):
    from dateutil.relativedelta import relativedelta

    if price.interval == "year":
        return end - relativedelta(years=price.interval_count)
    return end - relativedelta(months=price.interval_count)


def buy_addon(sub, addon, quantity=1, actor=None, idempotency_key="", now=None):
    """Create a pending add-on purchase and its invoice. Active once the invoice is paid."""
    now = now or timezone.now()
    if isinstance(addon, str):
        addon = AddOn.objects.get(code=addon)
    with transaction.atomic():
        sub = _lock(sub)
        if idempotency_key:
            earlier = sub.addons.filter(idempotency_key=idempotency_key).first()
            if earlier is not None:
                return earlier, earlier.invoices.order_by("-pk").first()
        quote = addon_quote(sub, addon, quantity, now)
        purchase = SubscriptionAddOn.objects.create(
            subscription=sub, addon=addon, quantity=quantity, unit_price=addon.price,
            idempotency_key=idempotency_key or "",
        )
        if quote["period_end"]:
            description = f"{addon.name} — {_fmt_period(now, quote['period_end'])}"
        else:
            description = addon.name
        invoice = _create_invoice(
            sub, I.Kind.ADDON,
            [_line(description, quantity, addon.price, quote["subtotal"], "addon", None)],
            now + timedelta(days=int(conf.get("PURCHASE_INVOICE_DAYS"))),
            purchase=purchase, start=I.Start.NOW, period_start=now, period_end=quote["period_end"],
        )
        log_event(sub, "addon_requested", {"addon": addon.code, "quantity": quantity, "invoice": invoice.number},
                  actor=actor)
    return purchase, invoice


def remove_addon(purchase, actor=None, now=None):
    """Pending: voided now. Active recurring: ends at the end of the current period."""
    now = now or timezone.now()
    with transaction.atomic():
        purchase = SubscriptionAddOn.objects.select_for_update().select_related("subscription", "addon").get(pk=purchase.pk)
        sub = purchase.subscription
        if purchase.status == A.PENDING_PAYMENT:
            for invoice in purchase.invoices.filter(status=I.Status.OPEN):
                _void(invoice)
            purchase.status = A.VOID
            purchase.save(update_fields=["status"])
        elif purchase.status == A.ACTIVE:
            purchase.status = A.ENDING
            purchase.ends_at = sub.current_period_end or access_until(sub) or now
            purchase.save(update_fields=["status", "ends_at"])
            _refresh_open_period_invoice(sub)
        else:
            raise InvalidRequest("This add-on has already ended.")
        log_event(sub, "addon_removed", {"addon": purchase.addon.code, "ends_at": str(purchase.ends_at)}, actor=actor)
    _changed(sub)
    return purchase


def _refresh_open_period_invoice(sub):
    """Rebuild the open next-period invoice after add-ons changed."""
    for invoice in sub.invoices.filter(status=I.Status.OPEN, kind__in=PERIOD_KINDS).select_related("price__plan"):
        lines = _period_lines(sub, invoice.price, invoice.period_start, invoice.period_end)
        subtotal = quantize(sum((Decimal(line["amount"]) for line in lines), Decimal(0)))
        tax = tax_of(subtotal)
        if conf.tax_rate():
            lines.append(_line(conf.get("TAX_LABEL"), 1, tax, tax, "tax"))
        invoice.lines, invoice.subtotal, invoice.tax, invoice.total = lines, subtotal, tax, subtotal + tax
        invoice.save(update_fields=["lines", "subtotal", "tax", "total"])


# --- payment ---------------------------------------------------------------

def mark_invoice_paid(invoice, paid_ref="", paid_at=None, actor=None, payment=None):
    """Apply a paid invoice. Idempotent: paying a paid invoice again changes nothing."""
    paid_at = paid_at or timezone.now()
    with transaction.atomic():
        invoice = SubscriptionInvoice.objects.select_for_update().get(pk=getattr(invoice, "pk", invoice))
        if invoice.status == I.Status.PAID:
            return invoice
        sub = _lock(invoice.subscription)
        late_void = invoice.status == I.Status.VOID
        invoice.status = I.Status.PAID
        invoice.paid_at = paid_at
        invoice.paid_ref = paid_ref or ""
        invoice.save(update_fields=["status", "paid_at", "paid_ref"])
        _apply_paid(sub, invoice, paid_at)
        log_event(sub, "invoice_paid", {"invoice": invoice.number, "ref": paid_ref, "late_after_void": late_void},
                  actor=actor)
    _changed(sub)
    transaction.on_commit(lambda: _notify_once(
        sub, "payment_received",
        {"invoice": invoice, "plan_name": invoice_plan_name(invoice), "paid_at": paid_at, "payment": payment},
        f"payment_received:{invoice.pk}",
    ))
    return invoice


def _set_period(sub, price, start, end):
    sub.plan_id, sub.price = price.plan_id, price
    sub.current_period_start, sub.current_period_end = start, end
    sub.paid_through = max(end, sub.paid_through or end)
    sub.pending_price, sub.pending_from = None, None


def _reopen(sub):
    sub.status = S.ACTIVE
    sub.grace_ends_at = None
    sub.expired_at = None
    sub.cancel_at_period_end = False


def _apply_paid(sub, invoice, paid_at):
    kind = invoice.kind
    if kind == I.Kind.ADDON:
        purchase = invoice.addon_purchase
        if purchase.status in (A.PENDING_PAYMENT, A.VOID):
            purchase.status = A.ACTIVE
            purchase.started_at = paid_at
            purchase.save(update_fields=["status", "started_at"])
            _refresh_open_period_invoice(sub)
        return

    if kind == I.Kind.UPGRADE:
        if effective_status(sub, paid_at) in ENDED:
            # Paid after the subscription ended: treat as a fresh period on the new price.
            _set_period(sub, invoice.price, paid_at, price_period_end(paid_at, invoice.price))
            _reopen(sub)
        else:
            sub.plan_id, sub.price = invoice.price.plan_id, invoice.price
            sub.pending_price, sub.pending_from = None, None
        sub.save()
        _refresh_open_period_invoice(sub)
        return

    price = invoice.price
    status = effective_status(sub, paid_at)
    if invoice.start == I.Start.NOW or status in ENDED:
        # Start now (trial ends early) or re-activation after expiry: the period starts on payment.
        end = price_period_end(paid_at, price)
        if sub.trial_end and sub.trial_end > paid_at:
            sub.trial_end = paid_at
        sub.paid_through = None
        _set_period(sub, price, paid_at, end)
        _reopen(sub)
    elif status == S.TRIALING:
        # Paid for after the trial: limits change when the trial ends.
        sub.paid_through = invoice.period_end
        if price.pk != sub.price_id:
            sub.pending_price, sub.pending_from = price, invoice.period_start
    else:
        # Renewal (active or past due): the next period follows on without a gap.
        if status == S.ACTIVE and sub.current_period_end and invoice.period_start >= sub.current_period_end:
            sub.paid_through = invoice.period_end
            if price.pk != sub.price_id:
                sub.pending_price, sub.pending_from = price, invoice.period_start
        else:
            _set_period(sub, price, invoice.period_start, invoice.period_end)
            _reopen(sub)
    sub.save()


def void_invoice(invoice, actor=None):
    with transaction.atomic():
        invoice = SubscriptionInvoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != I.Status.OPEN:
            raise InvoiceNotPayable("Only an open invoice can be voided.")
        _void(invoice)
        log_event(invoice.subscription, "invoice_voided_by_admin", {"invoice": invoice.number}, actor=actor)
    return invoice


# --- scheduled jobs ----------------------------------------------------------

def _live():
    return Subscription.objects.exclude(status__in=ENDED).select_related("plan", "price__plan", "pending_price__plan")


def issue_due_invoices(now=None):
    """First / renewal invoices INVOICE_LEAD_DAYS before the trial or period ends."""
    now = now or timezone.now()
    lead = timedelta(days=int(conf.get("INVOICE_LEAD_DAYS")))
    issued = 0
    for sub in _live():
        if sub.cancel_at_period_end:
            continue
        status = effective_status(sub, now)
        until = access_until(sub)
        if until is None or status not in (S.TRIALING, S.ACTIVE) or until - lead > now:
            continue
        if sub.invoices.filter(kind__in=PERIOD_KINDS, period_start__gte=until).exclude(status=I.Status.VOID).exists():
            continue
        with transaction.atomic():
            sub = _lock(sub)
            price = sub.pending_price or sub.price
            if not price.is_active:
                price = price.plan.current_price(price.interval) or price
            kind = I.Kind.FIRST if status == S.TRIALING else I.Kind.RENEWAL
            period_end = price_period_end(until, price)
            _create_invoice(
                sub, kind, _period_lines(sub, price, until, period_end), until,
                price=price, period_start=until, period_end=period_end,
            )
        issued += 1
    return issued


def advance_statuses(now=None):
    """Write the effective status, roll paid periods forward, end add-ons, send status emails."""
    now = now or timezone.now()
    changed = 0
    for sub in _live():
        with transaction.atomic():
            sub = _lock(sub)
            before = sub.status
            _roll(sub, now)
            status = effective_status(sub, now)
            if status == S.PAST_DUE and sub.status != S.PAST_DUE:
                sub.status = S.PAST_DUE
                sub.grace_ends_at = grace_end(sub)
                sub.save(update_fields=["status", "grace_ends_at", "updated_at"])
                log_event(sub, "past_due", {"grace_ends_at": sub.grace_ends_at.isoformat()})
                _after(lambda s=sub: _notify_overdue(s.pk, now))
            elif status in ENDED and sub.status not in ENDED:
                sub.status = status
                sub.expired_at = now
                sub.save(update_fields=["status", "expired_at", "updated_at"])
                log_event(sub, status)
                _after(lambda s=sub: _notify_expired(s.pk))
            elif status in (S.ACTIVE, S.TRIALING) and sub.status != status:
                sub.status = status
                sub.save(update_fields=["status", "updated_at"])
            if sub.status != before:
                changed += 1
        _changed(sub)
    _end_addons(now)
    _void_stale_purchases(now)
    return changed


def _after(fn):
    transaction.on_commit(fn)


def _roll(sub, now):
    """Move into the paid next period once the current one (or the trial) is over."""
    updated = False
    while True:
        boundary = sub.current_period_end if sub.current_period_end else sub.trial_end
        if not (boundary and sub.paid_through and now >= boundary and sub.paid_through > boundary):
            break
        paid = sub.invoices.filter(
            status=I.Status.PAID, kind__in=PERIOD_KINDS, period_start__gte=boundary,
        ).order_by("period_start").first()
        price = paid.price if paid else (sub.pending_price or sub.price)
        end = paid.period_end if paid else min(sub.paid_through, price_period_end(boundary, price))
        sub.plan_id, sub.price = price.plan_id, price
        sub.current_period_start, sub.current_period_end = boundary, end
        if sub.pending_from and sub.pending_from <= boundary:
            sub.pending_price, sub.pending_from = None, None
        sub.status = S.ACTIVE
        updated = True
    if updated:
        sub.save()
        log_event(sub, "period_started", {"start": sub.current_period_start.isoformat(),
                                          "end": sub.current_period_end.isoformat(), "plan": sub.price.plan.code})
    elif sub.pending_from and now >= sub.pending_from and sub.pending_price_id:
        # Scheduled downgrade reached its date without a paid next period: switch the plan anyway.
        sub.plan_id, sub.price = sub.pending_price.plan_id, sub.pending_price
        sub.pending_price, sub.pending_from = None, None
        sub.save()


def _end_addons(now):
    for purchase in SubscriptionAddOn.objects.filter(status=A.ENDING, ends_at__lte=now):
        purchase.status = A.ENDED
        purchase.save(update_fields=["status"])
        _changed(purchase.subscription)


def _void_stale_purchases(now):
    """Add-on and upgrade invoices not paid in time are voided (start-now first invoices too)."""
    stale = SubscriptionInvoice.objects.filter(
        status=I.Status.OPEN, due_at__lt=now,
    ).filter(kind__in=(I.Kind.ADDON, I.Kind.UPGRADE)) | SubscriptionInvoice.objects.filter(
        status=I.Status.OPEN, due_at__lt=now, start=I.Start.NOW,
    )
    for invoice in stale.distinct():
        with transaction.atomic():
            _void(invoice)


def _open_period_invoice(sub):
    return sub.invoices.filter(status=I.Status.OPEN, kind__in=PERIOD_KINDS).order_by("-pk").first()


def _notify_overdue(sub_id, now):
    sub = Subscription.objects.get(pk=sub_id)
    invoice = _open_period_invoice(sub)
    until = access_until(sub)
    _notify_once(
        sub, "payment_overdue",
        {"invoice": invoice, "days_overdue": max(0, (now - until).days) if until else 0,
         "grace_ends_at": sub.grace_ends_at},
        f"payment_overdue:{sub.pk}:{until.isoformat() if until else ''}",
    )


def _notify_expired(sub_id):
    sub = Subscription.objects.select_related("plan").get(pk=sub_id)
    _notify_once(
        sub, "expired", {"plan": sub.plan, "expired_at": sub.expired_at},
        f"expired:{sub.pk}:{sub.expired_at.isoformat()}",
    )


def _days_left(until, now):
    return max(0, math.ceil((until - now).total_seconds() / 86400))


def _threshold(days_left, thresholds):
    """The smallest reminder day that days_left has reached (send one, not all)."""
    reached = [d for d in thresholds if days_left <= d]
    return min(reached) if reached else None


def send_reminders(now=None):
    """Trial-ending and invoice-due reminders, each once per threshold."""
    now = now or timezone.now()
    sent = 0
    for sub in _live().filter(status=S.TRIALING):
        if effective_status(sub, now) != S.TRIALING or sub.paid_through:
            continue
        days_left = _days_left(sub.trial_end, now)
        threshold = _threshold(days_left, conf.get("TRIAL_REMINDER_DAYS"))
        if threshold is None:
            continue
        if _notify_once(
            sub, "trial_ending", {"plan": sub.plan, "trial_end": sub.trial_end, "days_left": days_left},
            f"trial_ending:{sub.pk}:{sub.trial_end.date()}:{threshold}",
        ):
            sent += 1
    invoices = SubscriptionInvoice.objects.filter(
        status=I.Status.OPEN, kind__in=PERIOD_KINDS, due_at__gt=now,
    ).select_related("subscription", "price__plan")
    for invoice in invoices:
        days_left = _days_left(invoice.due_at, now)
        threshold = _threshold(days_left, conf.get("RENEWAL_REMINDER_DAYS"))
        if threshold is None:
            continue
        if _notify_once(
            invoice.subscription, "invoice_reminder",
            {"invoice": invoice, "plan_name": invoice_plan_name(invoice), "days_left": days_left},
            f"invoice_reminder:{invoice.pk}:{threshold}",
        ):
            sent += 1
    return sent


def run_all(now=None):
    """Everything the scheduler runs, in order."""
    now = now or timezone.now()
    return {
        "statuses": advance_statuses(now),
        "invoices": issue_due_invoices(now),
        "reminders": send_reminders(now),
    }


# --- admin actions -----------------------------------------------------------

def extend_trial(sub, days, actor=None):
    with transaction.atomic():
        sub = _lock(sub)
        if sub.trial_end is None:
            raise InvalidRequest("This subscription has no trial.")
        sub.trial_end = sub.trial_end + timedelta(days=days)
        if sub.status in ENDED or sub.status == S.PAST_DUE:
            sub.status = S.TRIALING
            sub.expired_at = None
            sub.grace_ends_at = None
        sub.save()
        for invoice in sub.invoices.filter(status=I.Status.OPEN, kind=I.Kind.FIRST, start=I.Start.PERIOD):
            _void(invoice)
        log_event(sub, "trial_extended", {"days": days, "trial_end": sub.trial_end.isoformat()}, actor=actor)
    _changed(sub)
    return sub


def set_plan_without_charge(sub, price, actor=None, now=None):
    """Admin: move to another tier now, no invoice (e.g. a correction)."""
    now = now or timezone.now()
    with transaction.atomic():
        sub = _lock(sub)
        old = sub.price.plan.code
        sub.plan_id, sub.price = price.plan_id, price
        sub.pending_price, sub.pending_from = None, None
        sub.save()
        _refresh_open_period_invoice(sub)
        log_event(sub, "plan_set_by_admin", {"from": old, "to": price.plan.code}, actor=actor)
    _changed(sub)
    return sub


def set_override(subscriber, feature, value, reason="", expires_at=None, actor=None):
    from .models import FeatureOverride

    override, _ = FeatureOverride.objects.update_or_create(
        subscriber_id=subscriber.pk, feature=feature,
        defaults={"value": value, "reason": reason, "expires_at": expires_at},
    )
    sub = Subscription.objects.filter(subscriber_id=subscriber.pk).first()
    if sub:
        log_event(sub, "override_set", {"feature": feature.code, "value": value, "reason": reason}, actor=actor)
    entitlements.invalidate(subscriber.pk)
    return override


def remove_override(override, actor=None):
    subscriber_id = override.subscriber_id
    sub = Subscription.objects.filter(subscriber_id=subscriber_id).first()
    code = override.feature.code
    override.delete()
    if sub:
        log_event(sub, "override_removed", {"feature": code}, actor=actor)
    entitlements.invalidate(subscriber_id)
