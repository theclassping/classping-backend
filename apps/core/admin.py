from django.contrib import admin


class ReadOnlyAdmin(admin.ModelAdmin):
    """Django admin view for records that change only through services
    (payments, wallets): browse only, no add / change / delete."""

    def has_add_permission(self, request, *args):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
