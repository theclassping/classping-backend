"""
Settlement from the provider's settlement file (DANA: its Query Payment API
never reports settlement, so the hourly reconcile job skips it).

An admin uploads the daily file: ``preview_settlement_file`` matches every
line without changing anything, ``import_settlement_file`` applies it.
A paid checkout is settled (branch credit pending -> available) only when
the file's amount equals ours; every other mismatch is flagged for review,
never applied automatically.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from payment_aggregator import exceptions as provider_errors
from payment_aggregator.base import SettlementLine as ProviderLine
from payment_aggregator.base import SettlementLineType

from apps.payment_aggregator import PaymentAggregator

from . import exceptions as errors
from .models import GatewayPayment, SettlementFile, SettlementLine
from .services import flag_gateway_payment_for_review, mark_gateway_payment_settled

logger = logging.getLogger(__name__)

Result = SettlementLine.Result
CLOSED_UNPAID = (GatewayPayment.Status.CANCELLED, GatewayPayment.Status.EXPIRED, GatewayPayment.Status.FAILED)


@dataclass
class PlannedLine:
    line: ProviderLine
    result: str
    note: str = ""
    gateway_payment: Optional[GatewayPayment] = None

    @property
    def needs_review(self):
        return self.result in SettlementLine.REVIEW_RESULTS


@dataclass
class SettlementPreview:
    provider: str
    file_name: str
    sha256: str
    lines: List[PlannedLine] = field(default_factory=list)

    def count(self, *results):
        return sum(1 for planned in self.lines if planned.result in results)

    @property
    def settled_count(self):
        return self.count(Result.SETTLED)

    @property
    def review_count(self):
        return self.count(*SettlementLine.REVIEW_RESULTS)

    @property
    def unmatched_count(self):
        return self.count(Result.UNMATCHED)

    @property
    def settle_amount_total(self):
        amounts = [planned.line.settle_amount for planned in self.lines if planned.line.settle_amount is not None]
        return sum(amounts, Decimal("0")) if amounts else None

    @property
    def settled_total(self):
        """Classping amount moved to available by this file."""
        return sum(
            (planned.gateway_payment.amount for planned in self.lines if planned.result == Result.SETTLED),
            Decimal("0"),
        )


def _find(provider, provider_trx_id, reference_no):
    """Our checkout for a provider id, else for our own reference."""
    payments = GatewayPayment.objects.filter(Q(provider=provider) | Q(provider=""))
    if provider_trx_id:
        found = payments.filter(provider_trx_id=provider_trx_id).first()
        if found:
            return found
    if reference_no:
        return payments.filter(payment_no=reference_no).first()
    return None


def _plan_payment(provider, line, settled_here):
    payment = _find(provider, line.provider_trx_id, line.reference_no)
    if payment is None:
        return PlannedLine(line, Result.UNMATCHED, "No online payment with provider id {} / reference {}.".format(
            line.provider_trx_id or "-", line.reference_no or "-"))
    if payment.amount != line.amount:
        return PlannedLine(line, Result.AMOUNT_MISMATCH, "File amount {}, Classping amount {}; not settled.".format(
            line.amount, payment.amount), payment)
    if payment.status != GatewayPayment.Status.PAID:
        return PlannedLine(line, Result.NOT_PAID, "Settled by the provider but {} in Classping; not settled.".format(
            payment.get_status_display()), payment)
    if payment.settled_at or payment.pk in settled_here:
        return PlannedLine(line, Result.ALREADY_SETTLED, "", payment)
    settled_here.add(payment.pk)
    return PlannedLine(line, Result.SETTLED, "", payment)


def _plan_refund(provider, line):
    payment = _find(provider, line.original_trx_id, line.reference_no)
    if payment is None:
        return PlannedLine(line, Result.UNMATCHED, "Refund of unknown payment {}.".format(line.original_trx_id or "-"))
    if payment.refund_status == GatewayPayment.RefundStatus.REFUNDED and payment.refund_amount == line.amount:
        return PlannedLine(line, Result.CHECKED, "", payment)
    return PlannedLine(line, Result.REVIEW, "Provider refunded {}; Classping refund: {} {}.".format(
        line.amount, payment.get_refund_status_display() or "none", payment.refund_amount or ""), payment)


def _plan_cancel(provider, line):
    payment = _find(provider, line.original_trx_id, line.reference_no)
    if payment is None:
        return PlannedLine(line, Result.UNMATCHED, "Cancel of unknown payment {}.".format(line.original_trx_id or "-"))
    if payment.status in CLOSED_UNPAID:
        return PlannedLine(line, Result.CHECKED, "", payment)
    return PlannedLine(line, Result.REVIEW, "Provider cancelled {} but it is {} in Classping.".format(
        line.amount, payment.get_status_display()), payment)


def _plan(provider, line, settled_here):
    if line.type == SettlementLineType.PAYMENT:
        return _plan_payment(provider, line, settled_here)
    if line.type == SettlementLineType.REFUND:
        return _plan_refund(provider, line)
    if line.type == SettlementLineType.CANCEL:
        return _plan_cancel(provider, line)
    if line.type == SettlementLineType.ADJUSTMENT:
        payment = _find(provider, line.provider_trx_id, line.reference_no)
        return PlannedLine(line, Result.REVIEW, "Provider credit {} (ADJUSTMENT: it could not refund the payer); "
                           "check with the provider and refund the payer by hand.".format(line.amount), payment)
    return PlannedLine(line, Result.IGNORED, "{} is not used by Classping.".format(line.provider_type or "Line type"))


def _read(provider, content):
    aggregator = PaymentAggregator.using(provider)
    try:
        if not aggregator.settlement_via_file():
            raise errors.SettlementFileInvalid("{} has no settlement file to import.".format(provider))
        return aggregator.parse_settlement_file(content)
    except provider_errors.PaymentAggregatorError as error:
        raise errors.SettlementFileInvalid(error.message)


def preview_settlement_file(provider, file_name, content):
    """Match every line of ``content`` (bytes) without changing anything."""
    digest = hashlib.sha256(content).hexdigest()
    if SettlementFile.objects.filter(sha256=digest).exists():
        raise errors.SettlementFileAlreadyImported()
    preview = SettlementPreview(provider=provider, file_name=file_name, sha256=digest)
    settled_here = set()
    preview.lines = [_plan(provider, line, settled_here) for line in _read(provider, content)]
    return preview


def import_settlement_file(user, provider, file_name, content):
    """Apply a settlement file: settle matching paid checkouts, flag the
    rest for review, keep every line. All or nothing."""
    preview = preview_settlement_file(provider, file_name, content)
    with transaction.atomic():
        try:
            with transaction.atomic():
                settlement_file = SettlementFile.objects.create(
                    provider=provider, file_name=file_name[:255], sha256=preview.sha256, imported_by=user,
                )
        except IntegrityError:
            raise errors.SettlementFileAlreadyImported()

        rows = []
        for planned in preview.lines:
            line, payment = planned.line, planned.gateway_payment
            if planned.result == Result.SETTLED:
                settled_at = line.settled_at or timezone.now()
                payment = mark_gateway_payment_settled(payment.pk, settled_at=settled_at)
                if payment.settled_at is None:  # no longer paid (changed meanwhile)
                    planned.result, planned.note = Result.NOT_PAID, "Changed while importing; not settled."
                elif payment.settled_at != settled_at:  # settled meanwhile (manual / another import)
                    planned.result = Result.ALREADY_SETTLED
            elif planned.needs_review and payment is not None:
                payment = flag_gateway_payment_for_review(
                    payment.pk, "Settlement file {} line {}: {}".format(file_name, line.line_no, planned.note)
                )
            rows.append(SettlementLine(
                settlement_file=settlement_file,
                line_no=line.line_no,
                line_type=line.type,
                provider_type=line.provider_type,
                provider_trx_id=line.provider_trx_id,
                original_trx_id=line.original_trx_id,
                reference_no=line.reference_no,
                amount=line.amount,
                fee=line.fee,
                settle_amount=line.settle_amount,
                settled_at=line.settled_at,
                transaction_at=line.transaction_at,
                pay_method=line.pay_method,
                gateway_payment=payment,
                result=planned.result,
                note=planned.note,
                raw=line.raw,
            ))
        SettlementLine.objects.bulk_create(rows)
        settlement_file.line_count = len(rows)
        settlement_file.settled_count = preview.settled_count
        settlement_file.review_count = preview.review_count
        settlement_file.unmatched_count = preview.unmatched_count
        settlement_file.settle_amount_total = preview.settle_amount_total
        settlement_file.save(update_fields=[
            "line_count", "settled_count", "review_count", "unmatched_count", "settle_amount_total",
        ])
    logger.info(
        "Settlement file %s imported by user %s: %s lines, %s settled, %s review, %s unmatched",
        file_name, getattr(user, "pk", None), settlement_file.line_count, settlement_file.settled_count,
        settlement_file.review_count, settlement_file.unmatched_count,
    )
    return settlement_file
