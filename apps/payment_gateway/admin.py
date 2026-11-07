from django.contrib import admin

from .models import GatewayPayment, GatewayPaymentItem


class ReadOnlyAdmin(admin.ModelAdmin):
    """Gateway records change only through payment_gateway services."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class GatewayPaymentItemInline(admin.TabularInline):
    model = GatewayPaymentItem
    extra = 0
    can_delete = False
    fields = ["student_invoice", "amount", "is_active", "created_at"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(GatewayPayment)
class GatewayPaymentAdmin(ReadOnlyAdmin):
    list_display = [
        "payment_no",
        "branch",
        "student",
        "guardian",
        "channel_code",
        "status",
        "amount",
        "needs_review",
        "needs_refund",
        "created_at",
        "paid_at",
    ]
    list_filter = ["status", "payment_method", "provider", "needs_review", "needs_refund"]
    search_fields = ["payment_no", "provider_trx_id", "payment_code"]
    inlines = [GatewayPaymentItemInline]


@admin.register(GatewayPaymentItem)
class GatewayPaymentItemAdmin(ReadOnlyAdmin):
    list_display = ["gateway_payment", "student_invoice", "amount", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["gateway_payment__payment_no", "student_invoice__invoice_no"]
