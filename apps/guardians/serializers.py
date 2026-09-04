from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Guardian

User = get_user_model()


class GuardianSerializer(serializers.ModelSerializer):
    user_id = serializers.PrimaryKeyRelatedField(
        source="user",
        queryset=User.objects.all(),
    )

    class Meta:
        model = Guardian

        fields = [
            "id",
            "user_id",
            "name",
            "phone_number",
            "email",
            "image_data",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]


class GuardianInlineSerializer(serializers.ModelSerializer):
    # Creates the login User account together with the Guardian record.
    # If user with email already exists, it's handled in StudentSerializer._sync_student_guardians()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(write_only=True, required=True)
    last_name = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = Guardian
        fields = [
            "email",
            "password",
            "first_name",
            "last_name",
            "phone_number",
            "image_data",
        ]

    def create(self, validated_data):
        password = validated_data.pop("password")
        first_name = validated_data.pop("first_name")
        last_name = validated_data.pop("last_name")

        user = User.objects.create_user(
            email=validated_data["email"],
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=User.Role.PARENT,
        )

        # Combine first_name and last_name for Guardian.name field
        name = f"{first_name} {last_name}"

        return Guardian.objects.create(user=user, name=name, **validated_data)