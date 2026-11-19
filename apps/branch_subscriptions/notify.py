"""
Subscription emails through Mailjet, to the branch email and every active
staff member of the branch (so they can remind each other).

Templates (settings.MAILJET_TEMPLATES): subscription_<event>. Variables are
ready-to-show strings. ``school_name`` keeps its Mailjet name but carries the
branch ("SD Harapan Bangsa – Main Campus"), and is sent to every template.
"""
import logging

from django.conf import settings
from django.utils import timezone

from apps.mailer.services import Mailer
from plan_subscriptions.notify import Notifier

from .access import branch_label

logger = logging.getLogger(__name__)

MONTHS = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def fmt_date(value):
    if not value:
        return ""
    local = timezone.localtime(value) if hasattr(value, "tzinfo") and getattr(value, "hour", None) is not None else value
    return f"{local.day} {MONTHS[local.month]} {local.year}"


def fmt_datetime(value):
    if not value:
        return ""
    local = timezone.localtime(value)
    return f"{fmt_date(local)}, {local:%H:%M} WIB"


def fmt_amount(value):
    return "Rp " + f"{int(round(value or 0)):,}".replace(",", ".")


def invoice_vars(invoice, plan_name):
    return {
        "invoice_number": invoice.number,
        "plan_name": plan_name,
        "period_start": fmt_date(invoice.period_start),
        "period_end": fmt_date(invoice.period_end),
        "due_date": fmt_date(invoice.due_at),
        "amount": fmt_amount(invoice.total),
    }


def build_variables(event, subscription, context):
    if event == "trial_started":
        return {
            "plan_name": context["plan"].name,
            "trial_start_date": fmt_date(context["trial_start"]),
            "trial_end_date": fmt_date(context["trial_end"]),
            "trial_days": str(context["trial_days"]),
        }
    if event == "trial_ending":
        return {
            "plan_name": context["plan"].name,
            "trial_end_date": fmt_date(context["trial_end"]),
            "days_left": str(context["days_left"]),
        }
    if event == "invoice_issued":
        return invoice_vars(context["invoice"], context["plan_name"])
    if event == "invoice_reminder":
        return {**invoice_vars(context["invoice"], context["plan_name"]), "days_left": str(context["days_left"])}
    if event == "payment_overdue":
        invoice = context.get("invoice")
        return {
            "invoice_number": invoice.number if invoice else "",
            "due_date": fmt_date(invoice.due_at) if invoice else "",
            "days_overdue": str(context.get("days_overdue", 0)),
            "grace_end_date": fmt_date(context.get("grace_ends_at")),
            "amount": fmt_amount(invoice.total) if invoice else "",
        }
    if event == "expired":
        return {"plan_name": context["plan"].name, "expired_date": fmt_date(context["expired_at"])}
    if event == "payment_received":
        invoice = context["invoice"]
        payment = context.get("payment") or {}
        return {
            "invoice_number": invoice.number,
            "plan_name": context["plan_name"],
            "period_start": fmt_date(invoice.period_start),
            "period_end": fmt_date(invoice.period_end),
            "paid_at": fmt_datetime(context.get("paid_at")),
            "payment_method": payment.get("payment_method") or "Transfer bank",
            "amount": fmt_amount(payment.get("amount") or invoice.total),
        }
    raise ValueError(f"Unknown subscription event {event}")


def recipients(branch):
    """[(email, name)]: the branch email first, then every active staff member; no duplicates."""
    seen = set()
    result = []
    if branch.email:
        seen.add(branch.email.lower())
        result.append((branch.email, branch.name))
    for staff in branch.staffs.filter(is_active=True).order_by("pk"):
        if staff.email and staff.email.lower() not in seen:
            seen.add(staff.email.lower())
            result.append((staff.email, f"{staff.first_name} {staff.last_name}".strip()))
    return result


class MailjetNotifier(Notifier):
    def send(self, event, subscription, context):
        template_id = settings.MAILJET_TEMPLATES.get(f"subscription_{event}")
        if not template_id:
            logger.info("No Mailjet template for subscription_%s; skipped", event)
            return
        if not settings.MAILJET_API_KEY:
            logger.info("Mailjet is not configured; subscription_%s for %s skipped", event, subscription.pk)
            return
        branch = subscription.subscriber
        variables = build_variables(event, subscription, context)
        variables["school_name"] = branch_label(branch)
        mailer = Mailer()
        failures = 0
        targets = recipients(branch)
        for email, name in targets:
            try:
                mailer.send_template(
                    to_email=email, to_name=name or email, template_id=template_id,
                    variables={"name": name or email, **variables},
                )
            except Exception:
                failures += 1
                logger.exception("subscription_%s to %s failed", event, email)
        if targets and failures == len(targets):
            raise RuntimeError(f"subscription_{event}: every recipient failed")
