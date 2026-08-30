from django.contrib import admin

from mptt.admin import MPTTModelAdmin

from .models import Location


@admin.register(Location)
class LocationAdmin(MPTTModelAdmin):
    list_display = ("id", "name", "code", "location_type", "parent", "level")
    search_fields = ("name", "code")
