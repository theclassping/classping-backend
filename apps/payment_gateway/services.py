"""
Payment gateway business logic.

Status changes: every change takes a row lock and re-checks the status
(GatewayPayment.can_transition_to), so the expiry job, provider webhooks and
cancellations can run at the same time without overwriting each other: the
second one to get the lock sees the new status and does nothing.

Checkout: invoices are row-locked and the checkout (with its active items,
which lock the invoices) is committed BEFORE the provider is called, so two
checkouts for the same invoice can never both create a billing; the HTTP call
never runs while database locks are held.
"""

import datetime
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Sequence

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.core.access import scope_queryset
from apps.core.phone import InvalidPhoneNumber, normalize_phone
from apps.core.webhooks import InvalidWebhook
from apps.payment_aggregator import PaymentAggregator
from apps.payment_aggregator import exceptions as provider_errors
from apps.payment_aggregator.base import (
    BillingRequest,
    BillingStatus,
    FeeBreakdown,
    SettlementStatus,
)
from apps.payment_aggregator.constants import (
    PAYMENT_DEADLINE_MINUTES,
    PAYMENT_EXPIRY_CHECK_DELAY_MINUTES,
)
from apps.payments.models import Payment
from apps.payments.services import invoice_locked_error
from apps.student_invoices.models import StudentInvoice
from apps.staffs.models import Staff
from apps.students.models import Student, StudentGuardian
from apps.users.models import User

from . import exceptions as errors
from .models import GatewayPayment, GatewayPaymentItem
from .selectors import get_active_checkout_for_invoice

logger = logging.getLogger(__name__)

# Branch staff who may cancel a checkout (e.g. the parent paid cash).
CANCEL_STAFF_TYPES = (Staff.StaffType.OFFICER, Staff.StaffType.PRINCIPAL)


# --- Status changes -------------------------------------------------------


def _lock(gateway_payment_id):
    return GatewayPayment.objects.select_for_update().get(pk=gateway_payment_id)


def _close_locked(gateway_payment, status, **fields):
    """Apply a closing status to a LOCKED checkout and release its invoices."""
    gateway_payment.status = status
    for name, value in fields.items():
        setattr(gateway_payment, name, value)
    gateway_payment.save(update_fields=["status", "updated_at", *fields])
    gateway_payment.items.filter(is_active=True).update(is_active=False)


def _close_gateway_payment(gateway_payment_id, status):
    """PENDING -> ``status`` (expired / failed). No-op when the status
    already changed."""
    with transaction.atomic():
        gateway_payment = _lock(gateway_payment_id)
        if gateway_payment.can_transition_to(status):
            _close_locked(gateway_payment, status)
    return gateway_payment


def mark_gateway_payment_expired(gateway_payment_id):
    """Used by the expiry job and the provider's expiry callback."""
    return _close_gateway_payment(gateway_payment_id, GatewayPayment.Status.EXPIRED)


def _invoice_open_for_gateway(invoice, manual_payment):
    """Whether a (possibly late) gateway payment may settle this invoice.

    Settle: no manual payment; a REJECTED manual payment (its proofs stay as
    history); a SUBMITTED manual payment without proofs. Otherwise (paid,
    COMPLETED manual payment, SUBMITTED with proofs awaiting staff review) the
    invoice is left untouched and the checkout is flagged needs_refund; the
    refund itself is manual (ops).
    """
    if invoice.status == StudentInvoice.Status.PAID:
        return False
    if manual_payment is None or manual_payment.status == Payment.Status.REJECTED:
        return True
    if manual_payment.status == Payment.Status.SUBMITTED:
        return not manual_payment.proofs.exists()
    return False


def mark_gateway_payment_paid(gateway_payment_id, paid_at=None):
    """The payer paid: settle every invoice still open, credit the branch
    (pending settlement) and email payment_completed per invoice.

    Works from PENDING and, for late payments, from EXPIRED / CANCELLED /
    FAILED. Already PAID: no-op (duplicate callbacks). An invoice already
    paid another way is left untouched and the checkout is flagged
    needs_refund: the full amount still goes to the branch balance and the
    school refunds the payer manually (no refund feature).
    """
    from apps.wallets.services import post_payment_credit

    paid_at = paid_at or timezone.now()
    with transaction.atomic():
        gateway_payment = _lock(gateway_payment_id)
        if not gateway_payment.can_transition_to(GatewayPayment.Status.PAID):
            return gateway_payment

        invoices = StudentInvoice.objects.select_for_update().filter(
            pk__in=gateway_payment.items.values("student_invoice_id")
        ).order_by("pk")
        settled, refund_invoice_nos = [], []
        for invoice in invoices:
            manual_payment = Payment.objects.select_for_update().filter(student_invoice=invoice).first()
            if not _invoice_open_for_gateway(invoice, manual_payment):
                refund_invoice_nos.append(invoice.invoice_no)
                continue
            # A rejected manual payment row becomes the gateway row (its
            # proofs stay as history); otherwise a new row is created.
            payment = manual_payment or Payment(student_invoice=invoice)
            payment.amount = invoice.total_amount
            payment.payment_method = gateway_payment.payment_method
            payment.payment_channel = Payment.PaymentChannel.PAYMENT_GATEWAY
            payment.gateway_payment = gateway_payment
            payment.status = Payment.Status.COMPLETED
            payment.paid_at = paid_at
            payment.verified_at = paid_at
            payment.verified_by = None
            payment.rejection_reason = None
            payment.save()
            invoice.status = StudentInvoice.Status.PAID
            invoice.amount_paid = invoice.total_amount
            invoice.save(update_fields=["status", "amount_paid", "updated_at"])
            settled.append(payment)

        gateway_payment.status = GatewayPayment.Status.PAID
        gateway_payment.paid_at = paid_at
        update_fields = ["status", "paid_at", "updated_at"]
        if refund_invoice_nos:
            gateway_payment.needs_refund = True
            gateway_payment.review_note = _append_note(
                gateway_payment.review_note,
                "Refund to the payer (school, manual cash): these invoices were already "
                "paid another way: " + ", ".join(refund_invoice_nos),
            )
            update_fields += ["needs_refund", "review_note"]
        gateway_payment.save(update_fields=update_fields)
        gateway_payment.items.filter(is_active=True).update(is_active=False)

        post_payment_credit(gateway_payment)
        _send_payment_emails_after_commit([payment.pk for payment in settled])
    return gateway_payment


def cancel_gateway_payment(user, gateway_payment_id, reason=""):
    """B5 / C1b: PENDING -> CANCELLED and release the invoices.

    Classping rule only: the provider is not called and invoices are not
    changed. Allowed for the student's guardians, the branch's officer /
    principal, and Classping admins.
    """
    gateway_payment = scope_queryset(GatewayPayment.objects.all(), user).filter(pk=gateway_payment_id).first()
    if gateway_payment is None:
        raise NotFound()
    if not _can_cancel(user, gateway_payment):
        raise errors.CancelForbidden()
    with transaction.atomic():
        gateway_payment = _lock(gateway_payment.pk)
        if gateway_payment.status != GatewayPayment.Status.PENDING:
            raise errors.GatewayPaymentNotPending()
        _close_locked(
            gateway_payment,
            GatewayPayment.Status.CANCELLED,
            cancelled_by=user,
            cancelled_at=timezone.now(),
            cancel_reason=(reason or "").strip(),
        )
    return gateway_payment


def _can_cancel(user, gateway_payment):
    role = str(getattr(user, "role", "")).upper()
    if user.is_superuser or role == User.Role.ADMIN:
        return True
    if role == User.Role.PARENT:
        guardian = getattr(user, "guardian", None)
        return guardian is not None and StudentGuardian.objects.filter(
            student_id=gateway_payment.student_id, guardian=guardian
        ).exists()
    staff = getattr(user, "staff", None)
    return (
        role == User.Role.STAFF
        and staff is not None
        and staff.branch_id == gateway_payment.branch_id
        and staff.staff_type in CANCEL_STAFF_TYPES
    )


def flag_gateway_payment_for_review(gateway_payment_id, note):
    with transaction.atomic():
        gateway_payment = _lock(gateway_payment_id)
        gateway_payment.needs_review = True
        gateway_payment.review_note = _append_note(gateway_payment.review_note, note)
        gateway_payment.save(update_fields=["needs_review", "review_note", "updated_at"])
    return gateway_payment


def _append_note(existing, note):
    stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    line = "[{}] {}".format(stamp, note)
    return "{}\n{}".format(existing, line).strip()


def apply_billing_result(gateway_payment, billing):
    """Apply the provider's status (callback, sync or expiry job) to a checkout."""
    if billing.status == BillingStatus.PAID:
        if billing.amount is not None and billing.amount != gateway_payment.amount:
            return flag_gateway_payment_for_review(
                gateway_payment.pk,
                "Provider amount {} does not match checkout amount {}; not settled.".format(
                    billing.amount, gateway_payment.amount
                ),
            )
        gateway_payment = mark_gateway_payment_paid(gateway_payment.pk, paid_at=billing.paid_at)
    if (
        gateway_payment.status == GatewayPayment.Status.PAID
        and billing.settlement_status == SettlementStatus.SETTLED
        and gateway_payment.settled_at is None
    ):
        gateway_payment = mark_gateway_payment_settled(gateway_payment.pk)
    return gateway_payment


def handle_payment_callback(raw_body, headers):
    """Webhook ("rintisan", "payment"). Rintisan calls back only when a billing
    is paid; expiry is decided by Classping's expiry job (no callback)."""
    try:
        billing = PaymentAggregator.parse_billing_callback(raw_body, headers)
    except (provider_errors.InvalidCallback, provider_errors.ProviderNotConfigured) as error:
        logger.warning("Rejected payment callback: %s", error)
        raise InvalidWebhook() from error

    gateway_payment = GatewayPayment.objects.filter(payment_no=billing.reference_no).first()
    if gateway_payment is None and billing.provider_trx_id:
        gateway_payment = GatewayPayment.objects.filter(provider_trx_id=billing.provider_trx_id).first()
    if gateway_payment is None:
        logger.error("Payment callback for unknown checkout %s / %s", billing.reference_no, billing.provider_trx_id)
        return {"status": "ignored"}

    GatewayPayment.objects.filter(pk=gateway_payment.pk).update(
        callback_payload=billing.raw, callback_received_at=timezone.now()
    )
    if not gateway_payment.provider_trx_id and billing.provider_trx_id:
        GatewayPayment.objects.filter(pk=gateway_payment.pk, provider_trx_id__isnull=True).update(
            provider_trx_id=billing.provider_trx_id
        )
    apply_billing_result(gateway_payment, billing)
    return {"status": "ok"}


def sync_gateway_payment(gateway_payment_id):
    """Admin "Sync status": ask the provider and apply what it reports. A
    pending checkout past its window gets the expiry job's check (paid ->
    settled, otherwise expired)."""
    gateway_payment = GatewayPayment.objects.get(pk=gateway_payment_id)
    if gateway_payment.status == GatewayPayment.Status.PENDING and timezone.now() >= gateway_payment.expires_at:
        return expire_gateway_payment(gateway_payment.pk)
    if not gateway_payment.provider_trx_id:
        return gateway_payment
    billing = PaymentAggregator.get_billing_status(gateway_payment.provider_trx_id)
    return apply_billing_result(gateway_payment, billing)


def mark_gateway_payment_settled(gateway_payment_id):
    """The provider disbursed the money to Classping's partner balance:
    move the branch credit from pending to available."""
    from apps.wallets.services import mark_payment_settled

    with transaction.atomic():
        gateway_payment = _lock(gateway_payment_id)
        if gateway_payment.status != GatewayPayment.Status.PAID or gateway_payment.settled_at:
            return gateway_payment
        settled_at = timezone.now()
        mark_payment_settled(gateway_payment, settled_at)
        gateway_payment.settled_at = settled_at
        gateway_payment.save(update_fields=["settled_at", "updated_at"])
    return gateway_payment


def reconcile_settlements():
    """Hourly job: settle paid checkouts the provider has disbursed."""
    settled = 0
    unsettled = GatewayPayment.objects.filter(
        status=GatewayPayment.Status.PAID, settled_at__isnull=True, provider_trx_id__isnull=False
    ).values_list("pk", "provider_trx_id")
    for gateway_payment_id, provider_trx_id in unsettled:
        try:
            billing = PaymentAggregator.get_billing_status(provider_trx_id)
        except provider_errors.PaymentAggregatorError:
            logger.exception("Settlement check failed for gateway payment %s", gateway_payment_id)
            continue
        if billing.settlement_status == SettlementStatus.SETTLED:
            mark_gateway_payment_settled(gateway_payment_id)
            settled += 1
    return settled


def _send_payment_emails_after_commit(payment_ids):
    if not payment_ids:
        return
    from .tasks import send_payment_completed_email_task

    def enqueue():
        for payment_id in payment_ids:
            try:
                send_payment_completed_email_task.delay(payment_id)
            except Exception:
                logger.exception("Could not queue payment email for payment %s", payment_id)

    transaction.on_commit(enqueue)


def mark_gateway_payment_failed(gateway_payment_id):
    """The provider billing could not be created; release the invoices."""
    return _close_gateway_payment(gateway_payment_id, GatewayPayment.Status.FAILED)


def payment_expires_at(now=None):
    """End of the payment window for a checkout made at ``now``."""
    return (now or timezone.now()) + datetime.timedelta(minutes=PAYMENT_DEADLINE_MINUTES)


def expiry_check_time(gateway_payment):
    return gateway_payment.expires_at + datetime.timedelta(minutes=PAYMENT_EXPIRY_CHECK_DELAY_MINUTES)


def expire_gateway_payment(gateway_payment_id, now=None):
    """Expiry job body: expire a PENDING checkout whose window has passed.

    The provider is asked first, OUTSIDE the row lock (an HTTP call must not
    hold the lock). ProviderUnavailable propagates so the task retries.
    """
    gateway_payment = GatewayPayment.objects.get(pk=gateway_payment_id)
    if gateway_payment.status != GatewayPayment.Status.PENDING:
        return gateway_payment
    if (now or timezone.now()) < gateway_payment.expires_at:
        return gateway_payment

    if gateway_payment.provider_trx_id:
        try:
            billing = PaymentAggregator.get_billing_status(gateway_payment.provider_trx_id)
        except provider_errors.BillingNotFound:
            billing = None
        if billing is not None and billing.status == BillingStatus.PAID:
            # Paid but the callback never arrived: settle, never expire.
            return apply_billing_result(gateway_payment, billing)

    return mark_gateway_payment_expired(gateway_payment.pk)


def schedule_gateway_payment_expiry(gateway_payment):
    """Queue the expiry job for after the payment window (after commit).

    Never fails the caller: without a broker (e.g. staging without Redis) or
    when publishing fails, the provider's expiry webhook still applies.
    """
    if not settings.CELERY_BROKER_URL and not settings.CELERY_TASK_ALWAYS_EAGER:
        logger.warning(
            "No Celery broker configured; expiry job for %s not queued",
            gateway_payment.payment_no,
        )
        return

    from .tasks import expire_gateway_payment_task

    payment_id = gateway_payment.pk
    eta = expiry_check_time(gateway_payment)

    def enqueue():
        try:
            expire_gateway_payment_task.apply_async(args=[payment_id], eta=eta)
        except Exception:
            logger.exception("Could not queue expiry job for gateway payment %s", payment_id)

    transaction.on_commit(enqueue)


# --- Payability -----------------------------------------------------------


class NotPayableReason:
    INVOICE_PAID = "INVOICE_PAID"
    MANUAL_PAYMENT_SUBMITTED = "MANUAL_PAYMENT_SUBMITTED"
    INVOICE_LOCKED = "INVOICE_LOCKED"
    GATEWAY_DISABLED = "GATEWAY_DISABLED"


PAYABLE_INVOICE_STATUSES = (StudentInvoice.Status.UNPAID, StudentInvoice.Status.OVERDUE)


@dataclass(frozen=True)
class InvoicePayability:
    invoice: StudentInvoice
    reason: Optional[str] = None
    locked_by: Optional[GatewayPayment] = None

    @property
    def payable(self):
        return self.reason is None


@dataclass(frozen=True)
class StudentPayability:
    student: Student
    branch_id: Optional[int]
    is_payment_gateway_enabled: bool
    invoices: List[InvoicePayability]
    payment_window_minutes: int = PAYMENT_DEADLINE_MINUTES


@dataclass(frozen=True)
class CheckoutQuote:
    student: Student
    branch_id: int
    invoices: List[StudentInvoice]
    invoice_total: Decimal
    channels: Sequence[FeeBreakdown]
    # Deadline if the payer checks out now (the checkout fixes the real one).
    expires_at: datetime.datetime
    payment_window_minutes: int = PAYMENT_DEADLINE_MINUTES


def _invoice_queryset():
    return StudentInvoice.objects.select_related(
        "fee_type",
        "class_student__student",
        "class_student__class_obj__branch",
    )


def _manual_payment(invoice):
    try:
        return invoice.payment
    except Payment.DoesNotExist:
        return None


def get_invoice_payability(invoice):
    """Whether ``invoice`` can be paid through the gateway, and if not, why."""
    payment = _manual_payment(invoice)
    if invoice.status == StudentInvoice.Status.PAID or (
        payment is not None and payment.status == Payment.Status.COMPLETED
    ):
        return InvoicePayability(invoice, NotPayableReason.INVOICE_PAID)
    if invoice.status == StudentInvoice.Status.PAYMENT_SUBMITTED or (
        payment is not None and payment.status == Payment.Status.SUBMITTED
    ):
        return InvoicePayability(invoice, NotPayableReason.MANUAL_PAYMENT_SUBMITTED)
    if invoice.status not in PAYABLE_INVOICE_STATUSES:
        return InvoicePayability(invoice, NotPayableReason.INVOICE_PAID)
    checkout = get_active_checkout_for_invoice(invoice.pk)
    if checkout is not None:
        return InvoicePayability(invoice, NotPayableReason.INVOICE_LOCKED, checkout)
    if not invoice.class_student.class_obj.branch.is_payment_gateway_enabled:
        return InvoicePayability(invoice, NotPayableReason.GATEWAY_DISABLED)
    return InvoicePayability(invoice)


def _ensure_payable(payability):
    if payability.payable:
        return
    if payability.reason == NotPayableReason.INVOICE_LOCKED:
        raise invoice_locked_error(payability.locked_by)
    if payability.reason == NotPayableReason.GATEWAY_DISABLED:
        raise errors.GatewayDisabled()
    raise errors.InvoiceNotPayable(
        "Invoice {} cannot be paid online ({}).".format(payability.invoice.invoice_no, payability.reason)
    )


def get_student_payability(user, student_id):
    """B0: every invoice of the student with its online-payability."""
    student = scope_queryset(Student.objects.select_related("branch"), user).filter(pk=student_id).first()
    if student is None:
        raise NotFound()
    invoices = list(
        _invoice_queryset().filter(class_student__student=student).order_by("due_date", "pk")
    )
    branch = student.branch or (invoices[0].class_student.class_obj.branch if invoices else None)
    return StudentPayability(
        student=student,
        branch_id=branch.pk if branch else None,
        is_payment_gateway_enabled=bool(branch and branch.is_payment_gateway_enabled),
        invoices=[get_invoice_payability(invoice) for invoice in invoices],
    )


def get_checkout_quote(user, invoice_ids):
    """B1 (and the validation of B2): invoices must be visible to ``user``,
    belong to one student / branch, and be payable."""
    invoice_ids = sorted(set(invoice_ids))
    invoices = list(scope_queryset(_invoice_queryset(), user).filter(pk__in=invoice_ids).order_by("pk"))
    if len(invoices) != len(invoice_ids):
        raise NotFound()
    if len({invoice.class_student.student_id for invoice in invoices}) > 1:
        raise errors.MixedStudent()
    if len({invoice.class_student.class_obj.branch_id for invoice in invoices}) > 1:
        raise errors.MixedBranch()
    for invoice in invoices:
        _ensure_payable(get_invoice_payability(invoice))

    invoice_total = sum((invoice.total_amount for invoice in invoices), Decimal("0"))
    return CheckoutQuote(
        student=invoices[0].class_student.student,
        branch_id=invoices[0].class_student.class_obj.branch_id,
        invoices=invoices,
        invoice_total=invoice_total,
        channels=PaymentAggregator.get_channels(invoice_total),
        expires_at=payment_expires_at(),
    )


# --- Checkout -------------------------------------------------------------


def _checkout_guardian(user):
    if str(getattr(user, "role", "")).upper() != User.Role.PARENT:
        raise errors.CheckoutForbidden()
    guardian = getattr(user, "guardian", None)
    if guardian is None:
        raise errors.CheckoutForbidden()
    return guardian


def _replay_checkout(gateway_payment, invoice_ids, channel_code):
    """Same Idempotency-Key: return the earlier checkout if the request matches."""
    earlier_ids = set(gateway_payment.items.values_list("student_invoice_id", flat=True))
    if earlier_ids != set(invoice_ids) or gateway_payment.channel_code != channel_code:
        raise errors.IdempotencyKeyReused()
    return gateway_payment


def _create_pending_checkout(guardian, quote, fee, idempotency_key, expires_at):
    with transaction.atomic():
        locked = list(
            _invoice_queryset().select_for_update(of=("self",)).filter(
                pk__in=[invoice.pk for invoice in quote.invoices]
            ).order_by("pk")
        )
        for invoice in locked:
            _ensure_payable(get_invoice_payability(invoice))

        gateway_payment = GatewayPayment.objects.create(
            # Replaced below once the id is known (PAY-YYYYMMDD-000123).
            payment_no="TMP-" + uuid.uuid4().hex,
            branch_id=quote.branch_id,
            student=quote.student,
            guardian=guardian,
            provider=PaymentAggregator.provider_name(),
            channel_code=fee.channel_code,
            payment_method=fee.payment_method,
            invoice_total=fee.invoice_total,
            transaction_fee=fee.transaction_fee,
            amount=fee.amount,
            idempotency_key=idempotency_key,
            deadline_date=timezone.localdate(expires_at),
            expires_at=expires_at,
        )
        gateway_payment.payment_no = "PAY-{:%Y%m%d}-{:06d}".format(timezone.localdate(), gateway_payment.pk)
        gateway_payment.save(update_fields=["payment_no"])
        GatewayPaymentItem.objects.bulk_create(
            [
                GatewayPaymentItem(
                    gateway_payment=gateway_payment,
                    student_invoice=invoice,
                    amount=invoice.total_amount,
                )
                for invoice in locked
            ]
        )
    return gateway_payment


def _request_billing(billing_request):
    try:
        return PaymentAggregator.create_billing(billing_request)
    except provider_errors.DuplicateBilling as error:
        # Retried after a timeout: the billing already exists, fetch it.
        return PaymentAggregator.get_billing_status(error.provider_trx_id)


def _create_provider_billing(gateway_payment, guardian, payer_phone, quote):
    billing_request = BillingRequest(
        reference_no=gateway_payment.payment_no,
        channel_code=gateway_payment.channel_code,
        amount=gateway_payment.amount,
        invoice_date=timezone.localdate(),
        expires_at=gateway_payment.expires_at,
        payer_name=guardian.name,
        payer_phone=payer_phone,
        identifier=gateway_payment.payment_no,
        note=", ".join(invoice.invoice_no for invoice in quote.invoices),
    )
    try:
        billing = _request_billing(billing_request)
    except provider_errors.InvalidPayerPhone:
        mark_gateway_payment_failed(gateway_payment.pk)
        raise errors.PayerPhoneInvalid(gateway_payment_id=gateway_payment.pk)
    except provider_errors.ProviderRejected as error:
        logger.warning("Billing %s rejected: %s", gateway_payment.payment_no, error.provider_message)
        mark_gateway_payment_failed(gateway_payment.pk)
        raise errors.ProviderRejected(gateway_payment_id=gateway_payment.pk)
    except provider_errors.PaymentAggregatorError:
        logger.exception("Billing %s could not be created", gateway_payment.payment_no)
        mark_gateway_payment_failed(gateway_payment.pk)
        raise errors.ProviderUnavailable(gateway_payment_id=gateway_payment.pk)

    with transaction.atomic():
        GatewayPayment.objects.filter(pk=gateway_payment.pk).update(
            provider_trx_id=billing.provider_trx_id or None,
            payment_code=billing.payment_code,
            payment_link=billing.payment_link,
            billing_url=billing.billing_url,
            provider_response=billing.raw,
            updated_at=timezone.now(),
        )
        gateway_payment.refresh_from_db()
        schedule_gateway_payment_expiry(gateway_payment)
    return gateway_payment


def create_gateway_checkout(user, invoice_ids, channel_code, idempotency_key):
    """B2. Returns (gateway_payment, created)."""
    guardian = _checkout_guardian(user)
    earlier = GatewayPayment.objects.filter(guardian=guardian, idempotency_key=idempotency_key).first()
    if earlier is not None:
        return _replay_checkout(earlier, invoice_ids, channel_code), False

    quote = get_checkout_quote(user, invoice_ids)
    if not StudentGuardian.objects.filter(student=quote.student, guardian=guardian).exists():
        raise errors.CheckoutForbidden()
    try:
        payer_phone = normalize_phone(guardian.phone_number)
    except InvalidPhoneNumber:
        raise errors.PayerPhoneInvalid()
    try:
        fee = PaymentAggregator.calculate_transaction_fee(channel_code, quote.invoice_total)
    except provider_errors.ChannelNotAvailable:
        raise errors.ChannelNotAvailable(
            "Channel {} is not available for this amount.".format(channel_code)
        )

    expires_at = payment_expires_at()
    try:
        gateway_payment = _create_pending_checkout(guardian, quote, fee, idempotency_key, expires_at)
    except IntegrityError:
        # The same Idempotency-Key was submitted twice at the same moment.
        earlier = GatewayPayment.objects.filter(guardian=guardian, idempotency_key=idempotency_key).first()
        if earlier is None:
            raise
        return _replay_checkout(earlier, invoice_ids, channel_code), False

    return _create_provider_billing(gateway_payment, guardian, payer_phone, quote), True
