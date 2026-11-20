"""Django admin: a fallback for hosts without their own back office."""
from django.contrib import admin

from .models import (
    AddOn,
    AddOnFeature,
    CatalogChange,
    Feature,
    FeatureOverride,
    Plan,
    PlanFeature,
    PlanPrice,
    Subscription,
    SubscriptionAddOn,
    SubscriptionEvent,
    SubscriptionInvoice,
)


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "unit", "on_expiry", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")


class PlanPriceInline(admin.TabularInline):
    model = PlanPrice
    extra = 0
    readonly_fields = ("created_at",)


class PlanFeatureInline(admin.TabularInline):
    model = PlanFeature
    extra = 0


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "trial_days", "is_public", "is_active", "sort_order")
    inlines = [PlanPriceInline, PlanFeatureInline]


class AddOnFeatureInline(admin.TabularInline):
    model = AddOnFeature
    extra = 0


@admin.register(AddOn)
class AddOnAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "billing", "price", "max_quantity", "is_active")
    filter_horizontal = ("plans",)
    inlines = [AddOnFeatureInline]


class SubscriptionAddOnInline(admin.TabularInline):
    model = SubscriptionAddOn
    extra = 0
    readonly_fields = ("addon", "quantity", "unit_price", "status", "started_at", "ends_at", "created_at")
    can_delete = False


class InvoiceInline(admin.TabularInline):
    model = SubscriptionInvoice
    extra = 0
    fields = ("number", "kind", "period_start", "period_end", "total", "status", "due_at", "paid_at", "paid_ref")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("subscriber", "plan", "status", "trial_end", "current_period_end", "paid_through")
    list_filter = ("status", "plan")
    raw_id_fields = ("subscriber",)
    inlines = [SubscriptionAddOnInline, InvoiceInline]


@admin.register(SubscriptionInvoice)
class SubscriptionInvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "subscription", "kind", "total", "status", "due_at", "paid_at")
    list_filter = ("status", "kind")
    search_fields = ("number", "paid_ref")
    readonly_fields = ("lines",)


@admin.register(FeatureOverride)
class FeatureOverrideAdmin(admin.ModelAdmin):
    list_display = ("subscriber", "feature", "value", "reason", "expires_at")
    raw_id_fields = ("subscriber",)


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = ("subscription", "type", "created_at", "actor")
    list_filter = ("type",)


@admin.register(CatalogChange)
class CatalogChangeAdmin(admin.ModelAdmin):
    list_display = ("object_type", "object_id", "action", "actor", "created_at")
