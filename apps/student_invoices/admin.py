from django.contrib import admin

from .models import StudentInvoice


@admin.register(StudentInvoice)
class StudentInvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "invoice_no",
        "class_student",
        "fee_type",
        "invoice_date",
        "due_date",
        "status",
        "total_amount",
        "currency",
    ]
    list_filter = [
        "status",
        "currency",
    ]
    search_fields = [
        "invoice_no",
        "class_student__student__first_name",
        "class_student__student__last_name",
    ]
