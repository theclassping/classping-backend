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
from apps.payment_aggregator import PaymentAggregator
from apps.payment_aggregator import exceptions as provider_errors
from apps.payment_aggregator.base import BillingRequest, BillingStatus, FeeBreakdown
from apps.payment_aggregator.constants import (
    PAYMENT_DEADLINE_MINUTES,
    PAYMENT_EXPIRY_CHECK_DELAY_MINUTES,
)
from apps.payments.models import Payment
from apps.payments.services import invoice_locked_error
from apps.student_invoices.models import StudentInvoice
from apps.students.models import Student, StudentGuardian
from apps.users.models import User

from . import exceptions as errors
from .models import GatewayPayment, GatewayPaymentItem
from .selectors import get_active_checkout_for_invoice

logger = logging.getLogger(__name__)


# --- Status changes -------------------------------------------------------


def _close_gateway_payment(gateway_payment_id, status):
    """PENDING -> ``status`` (expired / failed / cancelled) and release the
    invoices (items inactive). No-op when the status already changed."""
    with transaction.atomic():
        gateway_payment = GatewayPayment.objects.select_for_update().get(pk=gateway_payment_id)
        if not gateway_payment.can_transition_to(status):
            return gateway_payment
        gateway_payment.status = status
        gateway_payment.save(update_fields=["status", "updated_at"])
        gateway_payment.items.filter(is_active=True).update(is_active=False)
    return gateway_payment


def mark_gateway_payment_expired(gateway_payment_id):
    """Used by the expiry job and (Step 5) the provider's expiry webhook."""
    return _close_gateway_payment(gateway_payment_id, GatewayPayment.Status.EXPIRED)


def mark_gateway_payment_failed(gateway_payment_id):
    """The provider billing could not be created; release the invoices."""
    return _close_gateway_payment(gateway_payment_id, GatewayPayment.Status.FAILED)


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
            # Settled by mark_gateway_payment_paid() (Step 5); never expire a paid billing.
            logger.warning(
                "Gateway payment %s is paid at the provider but still pending",
                gateway_payment.payment_no,
            )
            return gateway_payment

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

    expires_at = timezone.now() + datetime.timedelta(minutes=PAYMENT_DEADLINE_MINUTES)
    try:
        gateway_payment = _create_pending_checkout(guardian, quote, fee, idempotency_key, expires_at)
    except IntegrityError:
        # The same Idempotency-Key was submitted twice at the same moment.
        earlier = GatewayPayment.objects.filter(guardian=guardian, idempotency_key=idempotency_key).first()
        if earlier is None:
            raise
        return _replay_checkout(earlier, invoice_ids, channel_code), False

    return _create_provider_billing(gateway_payment, guardian, payer_phone, quote), True
