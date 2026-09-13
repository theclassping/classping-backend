from django.contrib import admin

from .models import FeeType, FeeTypeClass


@admin.register(FeeType)
class FeeTypeAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "branch",
        "name",
        "amount",
        "currency",
        "is_recurring",
        "recurring_frequency",
        "is_active",
    ]
    list_filter = [
        "is_recurring",
        "recurring_frequency",
        "is_active",
    ]
    search_fields = [
        "name",
        "branch__name",
    ]


@admin.register(FeeTypeClass)
class FeeTypeClassAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "fee_type",
        "class_obj",
        "created_at",
    ]
    list_filter = [
        "class_obj__branch",
    ]
    search_fields = [
        "fee_type__name",
        "class_obj__name",
    ]
