from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin

from .models import BranchWallet, LedgerEntry


@admin.register(BranchWallet)
class BranchWalletAdmin(ReadOnlyAdmin):
    list_display = ["branch", "available_balance", "pending_balance", "updated_at"]


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "branch", "entry_type", "amount", "settlement_status", "gateway_payment"]
    list_filter = ["entry_type", "settlement_status"]
    search_fields = ["gateway_payment__payment_no", "note"]
