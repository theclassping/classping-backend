from rest_framework import serializers

from .models import Guardian


class GuardianSerializer(serializers.ModelSerializer):

    class Meta:
        model = Guardian

        fields = [
            "id",
            "user",
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