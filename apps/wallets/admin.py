from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import BranchWallet, LedgerEntry, PayoutAccount, Withdrawal


@admin.register(BranchWallet)
class BranchWalletAdmin(ReadOnlyAdmin):
    list_display = ["branch", "available_balance", "pending_balance", "updated_at"]


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "branch", "entry_type", "amount", "settlement_status", "gateway_payment", "withdrawal"]
    list_filter = ["entry_type", "settlement_status"]
    search_fields = ["gateway_payment__payment_no", "withdrawal__withdrawal_no", "note"]


@admin.register(PayoutAccount)
class PayoutAccountAdmin(ReadOnlyAdmin):
    list_display = ["branch", "bank_code", "account_number", "account_holder_name", "updated_at"]
    search_fields = ["account_number", "account_holder_name"]


@admin.register(Withdrawal)
class WithdrawalAdmin(ReadOnlyAdmin):
    list_display = ["withdrawal_no", "branch", "status", "amount", "fee", "transfer_amount", "needs_review", "created_at"]
    list_filter = ["status", "needs_review"]
    search_fields = ["withdrawal_no", "provider_disbursement_id"]
