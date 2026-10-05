from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from apps.users.managers import generate_temporary_password
from .models import Staff

User = get_user_model()


class StaffSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
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

        expected_role = (
            User.Role.TEACHER
            if staff_type == Staff.StaffType.TEACHER
            else User.Role.STAFF
        )
        if user and str(user.role).lower() != expected_role.lower():
            raise serializers.ValidationError({
                "user": f"This staff type requires a user with the {expected_role} role."
            })

        if (
            self.instance is None
            and user is None
            and User.objects.filter(email=attrs.get("email")).exists()
        ):
            raise serializers.ValidationError({
                "email": "A user with this email already exists. Provide its user ID instead."
            })

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        user = validated_data.pop("user", None)
        if user is None:
            staff_type = validated_data["staff_type"]
            user = User.objects.create_user(
                email=validated_data["email"],
                temporary_password=generate_temporary_password(),
                first_name=validated_data["first_name"],
                last_name=validated_data["last_name"],
                role=(
                    User.Role.TEACHER
                    if staff_type == Staff.StaffType.TEACHER
                    else User.Role.STAFF
                ),
                is_active=validated_data.get("is_active", True),
            )

        return Staff.objects.create(user=user, **validated_data)
