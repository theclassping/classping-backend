"""
Branch wallet and ledger. Every balance change locks the wallet row and
writes the ledger entry in the same transaction (call inside atomic()).
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import BranchWallet, LedgerEntry


def lock_wallet(branch_id):
    BranchWallet.objects.get_or_create(branch_id=branch_id)
    return BranchWallet.objects.select_for_update().get(branch_id=branch_id)


def post_payment_credit(gateway_payment):
    """Credit a paid checkout's full invoice total to its branch as PENDING
    settlement (call inside the transaction that marks it paid).

    The whole invoice_total is credited, also for invoices flagged
    needs_refund: the money did arrive, and the school refunds the payer
    itself (manually, in cash). Classping takes no fee of its own.
    """
    wallet = lock_wallet(gateway_payment.branch_id)
    LedgerEntry.objects.create(
        branch_id=gateway_payment.branch_id,
        entry_type=LedgerEntry.EntryType.PAYMENT_CREDIT,
        amount=gateway_payment.invoice_total,
        gateway_payment=gateway_payment,
        settlement_status=LedgerEntry.SettlementStatus.PENDING_SETTLEMENT,
        note=gateway_payment.payment_no,
    )
    wallet.pending_balance += gateway_payment.invoice_total
    wallet.save(update_fields=["pending_balance", "updated_at"])


def mark_payment_settled(gateway_payment, settled_at=None):
    """Provider settled the checkout: pending -> available. Idempotent."""
    settled_at = settled_at or timezone.now()
    with transaction.atomic():
        wallet = lock_wallet(gateway_payment.branch_id)
        entries = list(
            LedgerEntry.objects.select_for_update().filter(
                gateway_payment=gateway_payment,
                settlement_status=LedgerEntry.SettlementStatus.PENDING_SETTLEMENT,
            )
        )
        if not entries:
            return False
        net = sum((entry.amount for entry in entries), Decimal("0"))
        LedgerEntry.objects.filter(pk__in=[entry.pk for entry in entries]).update(
            settlement_status=LedgerEntry.SettlementStatus.SETTLED,
            settled_at=settled_at,
        )
        wallet.pending_balance -= net
        wallet.available_balance += net
        wallet.save(update_fields=["pending_balance", "available_balance", "updated_at"])
    return True
