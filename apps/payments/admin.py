from django.contrib import admin

from .models import Payment, PaymentProof


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "student_invoice",
        "amount",
        "payment_method",
        "status",
        "submitted_at",
        "verified_at",
        "verified_by",
    ]
    list_filter = [
        "status",
        "payment_method",
    ]
    search_fields = [
        "student_invoice__invoice_no",
    ]


@admin.register(PaymentProof)
class PaymentProofAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "payment",
        "uploaded_at",
    ]
    search_fields = [
        "payment__student_invoice__invoice_no",
    ]