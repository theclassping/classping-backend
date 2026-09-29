from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Staff

User = get_user_model()


class StaffSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=True,
    )

    staff_type_display = serializers.CharField(
        source="get_staff_type_display",
        read_only=True,
    )

    class Meta:
        model = Staff

        fields = [
            "id",
            "branch",
            "user",
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

    def validate(self, attrs):
        staff_type = attrs.get("staff_type", getattr(self.instance, "staff_type", None))
        user = attrs.get("user", getattr(self.instance, "user", None))

        if not user:
            raise serializers.ValidationError({"user": "A user account is required for every staff member."})

        expected_role = (
            User.Role.TEACHER
            if staff_type == Staff.StaffType.TEACHER
            else User.Role.STAFF
        )
        if user.role != expected_role:
            raise serializers.ValidationError({
                "user": f"This staff type requires a user with the {expected_role} role."
            })

        return attrs