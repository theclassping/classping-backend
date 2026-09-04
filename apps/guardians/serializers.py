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
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = Guardian
        fields = [
            "email",
            "password",
            "name",
            "phone_number",
            "image_data",
        ]

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "A user with this email already exists."
            )
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")

        first_name, _, last_name = validated_data["name"].partition(" ")

        user = User.objects.create_user(
            email=validated_data["email"],
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=User.Role.PARENT,
        )

        return Guardian.objects.create(user=user, **validated_data)