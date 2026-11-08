from django.conf import settings
from django.db import models
from django.db.models import Q


class DestinationMixin:
    """Display helpers for models holding bank_code / account_number."""

    @property
    def bank_name(self):
        from apps.payment_aggregator import PaymentAggregator

        return PaymentAggregator.get_banks().get(self.bank_code, self.bank_code)

    @property
    def account_number_masked(self):
        return "****" + self.account_number[-4:] if self.account_number else ""


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


class PayoutAccount(DestinationMixin, models.Model):
    """A bank account a branch withdraws to. Saved automatically by the
    first withdrawal to it; a branch can have many."""

    branch = models.ForeignKey("schools.Branch", on_delete=models.CASCADE, related_name="payout_accounts")
    bank_code = models.CharField(max_length=30)
    account_number = models.CharField(max_length=30)
    # Sent to the provider as the recipient name.
    account_holder_name = models.CharField(max_length=100)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="payout_accounts",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payout_accounts"
        ordering = ["-updated_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "bank_code", "account_number"],
                name="uniq_payout_account_per_branch",
            ),
        ]

    def __str__(self):
        return f"{self.bank_code} {self.account_number_masked}"


class WithdrawalOtp(DestinationMixin, models.Model):
    """A pending withdrawal waiting for the OTP emailed to the branch.

    Stored in the database (not a cache) so it works on every environment
    and across workers. Only a hash of the code is kept.
    """

    reference = models.CharField(max_length=64, unique=True)
    branch = models.ForeignKey("schools.Branch", on_delete=models.CASCADE, related_name="withdrawal_otps")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="withdrawal_otps")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    bank_code = models.CharField(max_length=30)
    account_number = models.CharField(max_length=30)
    account_holder_name = models.CharField(max_length=100)
    code_hash = models.CharField(max_length=64)
    sent_to = models.EmailField()
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "withdrawal_otps"

    def __str__(self):
        return self.reference


class Withdrawal(DestinationMixin, models.Model):
    """A branch withdrawal sent to the provider as one disbursement.

    The provider deducts ``fee`` from ``amount``; the bank account receives
    ``transfer_amount``. Status changes only through wallets.services.
    """

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    # Sent to the provider as its reference (Rintisan reference_id).
    withdrawal_no = models.CharField(max_length=50, unique=True)
    branch = models.ForeignKey("schools.Branch", on_delete=models.PROTECT, related_name="withdrawals")
    payout_account = models.ForeignKey(
        PayoutAccount,
        on_delete=models.SET_NULL,
        related_name="withdrawals",
        blank=True,
        null=True,
    )
    # Snapshot of the destination (the payout account may be edited or deleted).
    bank_code = models.CharField(max_length=30)
    account_number = models.CharField(max_length=30)
    account_holder_name = models.CharField(max_length=100)

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    fee = models.DecimalField(max_digits=14, decimal_places=2)
    transfer_amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)

    provider = models.CharField(max_length=30)
    provider_disbursement_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    provider_status = models.CharField(max_length=10, blank=True, default="")
    provider_fee = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    provider_response = models.JSONField(blank=True, null=True)
    callback_payload = models.JSONField(blank=True, null=True)
    callback_received_at = models.DateTimeField(blank=True, null=True)

    needs_review = models.BooleanField(default=False)
    review_note = models.TextField(blank=True, default="")
    failure_reason = models.CharField(max_length=255, blank=True, default="")

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="withdrawals",
        blank=True,
        null=True,
    )
    fee_acknowledged_at = models.DateTimeField()
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "withdrawals"
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["branch", "created_at"], name="withdrawal_branch_created")]

    def __str__(self):
        return self.withdrawal_no


class LedgerEntry(models.Model):
    """Append-only branch money movements (credit +, debit -).

    Only settlement_status / settled_at of payment entries are ever updated.
    """

    class EntryType(models.TextChoices):
        PAYMENT_CREDIT = "payment_credit", "Payment credit"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        WITHDRAWAL_FEE = "withdrawal_fee", "Withdrawal fee"
        WITHDRAWAL_REVERSAL = "withdrawal_reversal", "Withdrawal reversal"
        WITHDRAWAL_FEE_REVERSAL = "withdrawal_fee_reversal", "Withdrawal fee reversal"
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
    withdrawal = models.ForeignKey(
        Withdrawal,
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
            # A withdrawal is debited / reversed exactly once.
            models.UniqueConstraint(
                fields=["withdrawal", "entry_type"],
                condition=Q(withdrawal__isnull=False),
                name="uniq_ledger_entry_type_per_withdrawal",
            ),
            models.CheckConstraint(check=~Q(amount=0), name="ledger_entry_amount_not_zero"),
        ]
        indexes = [models.Index(fields=["branch", "created_at"], name="ledger_branch_created")]

    def __str__(self):
        return f"{self.entry_type} {self.amount} ({self.branch_id})"
