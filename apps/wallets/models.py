from django.conf import settings
from django.db import models
from django.db.models import Q


class BranchWallet(models.Model):
    """Cached branch balance; the ledger is the source of truth.

    Changed only by wallets.services, always under a row lock and in the same
    transaction as the ledger entry that explains the change.
    """

    branch = models.OneToOneField(
        "schools.Branch",
        on_delete=models.PROTECT,
        related_name="wallet",
    )
    # Settled money the branch can withdraw.
    available_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # Paid by parents but not yet settled by the provider.
    pending_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "branch_wallets"
        constraints = [
            models.CheckConstraint(check=Q(available_balance__gte=0), name="branch_wallet_available_non_negative"),
            models.CheckConstraint(check=Q(pending_balance__gte=0), name="branch_wallet_pending_non_negative"),
        ]

    def __str__(self):
        return f"Wallet {self.branch_id}"


class LedgerEntry(models.Model):
    """Append-only branch money movements (credit +, debit -).

    Only settlement_status / settled_at of payment entries are ever updated.
    """

    class EntryType(models.TextChoices):
        PAYMENT_CREDIT = "payment_credit", "Payment credit"
        ADJUSTMENT = "adjustment", "Adjustment"

    class SettlementStatus(models.TextChoices):
        PENDING_SETTLEMENT = "pending_settlement", "Pending settlement"
        SETTLED = "settled", "Settled"

    branch = models.ForeignKey("schools.Branch", on_delete=models.PROTECT, related_name="ledger_entries")
    entry_type = models.CharField(max_length=30, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    gateway_payment = models.ForeignKey(
        "payment_gateway.GatewayPayment",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        blank=True,
        null=True,
    )
    settlement_status = models.CharField(
        max_length=30, choices=SettlementStatus.choices, blank=True, null=True
    )
    settled_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ledger_entries",
        blank=True,
        null=True,
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ledger_entries"
        ordering = ["-created_at", "-pk"]
        constraints = [
            # A paid checkout is credited exactly once (duplicate callbacks).
            models.UniqueConstraint(
                fields=["gateway_payment", "entry_type"],
                condition=Q(gateway_payment__isnull=False),
                name="uniq_ledger_entry_type_per_gateway_payment",
            ),
            models.CheckConstraint(check=~Q(amount=0), name="ledger_entry_amount_not_zero"),
        ]
        indexes = [models.Index(fields=["branch", "created_at"], name="ledger_branch_created")]

    def __str__(self):
        return f"{self.entry_type} {self.amount} ({self.branch_id})"
