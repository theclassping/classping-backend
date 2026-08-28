from rest_framework import serializers

from .models import FeeType


class FeeTypeSerializer(serializers.ModelSerializer):

    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
    )

    class Meta:
        model = FeeType

        fields = [
            "id",
            "branch",
            "branch_name",
            "name",
            "description",
            "amount",
            "is_recurring",
            "is_active",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "branch_name",
            "created_at",
            "updated_at",
        ]

    def validate_amount(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "Amount cannot be negative."
            )

        return value