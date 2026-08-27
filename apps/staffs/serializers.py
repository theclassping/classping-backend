from rest_framework import serializers

from .models import Staff


class StaffSerializer(serializers.ModelSerializer):
    staff_type_display = serializers.CharField(
        source="get_staff_type_display",
        read_only=True,
    )

    class Meta:
        model = Staff

        fields = [
            "id",
            "branch",
            "first_name",
            "last_name",
            "email",
            "phone",
            "staff_type",
            "staff_type_display",
            "hire_date",
            "qualification",
            "is_active",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "staff_type_display",
            "created_at",
            "updated_at",
        ]