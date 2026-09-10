from rest_framework import serializers

from .models import FeeType, FeeTypeClass


class FeeTypeClassSerializer(serializers.ModelSerializer):

    class_name = serializers.CharField(
        source="class_obj.name",
        read_only=True,
    )

    class Meta:
        model = FeeTypeClass

        fields = [
            "id",
            "fee_type",
            "class_obj",
            "class_name",
            "created_at",
        ]

        read_only_fields = [
            "id",
            "class_name",
            "created_at",
        ]


class FeeTypeSerializer(serializers.ModelSerializer):

    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
    )

    fee_type_classes = FeeTypeClassSerializer(
        many=True,
        read_only=True,
    )

    class_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        allow_empty=True,
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
            "currency",
            "is_recurring",
            "recurring_frequency",
            "is_active",
            "fee_type_classes",
            "class_ids",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "branch_name",
            "fee_type_classes",
            "created_at",
            "updated_at",
        ]

    def validate_amount(self, value):
        if value < 0:
            raise serializers.ValidationError(
                "Amount cannot be negative."
            )

        return value

    def validate(self, data):
        is_recurring = data.get("is_recurring", False)
        recurring_frequency = data.get("recurring_frequency")

        if is_recurring and not recurring_frequency:
            raise serializers.ValidationError(
                {
                    "recurring_frequency": "Recurring frequency is required when fee type is recurring."
                }
            )

        return data

    def create(self, validated_data):
        class_ids = validated_data.pop("class_ids", [])
        fee_type = super().create(validated_data)
        self._assign_classes(fee_type, class_ids)
        return fee_type

    def update(self, instance, validated_data):
        class_ids = validated_data.pop("class_ids", None)
        fee_type = super().update(instance, validated_data)

        if class_ids is not None:
            fee_type.fee_type_classes.all().delete()
            self._assign_classes(fee_type, class_ids)

        return fee_type

    def _assign_classes(self, fee_type, class_ids):
        from apps.classes.models import Class

        existing_ids = set(
            fee_type.fee_type_classes.values_list("class_obj_id", flat=True)
        )

        for class_id in set(class_ids):
            if class_id not in existing_ids:
                FeeTypeClass.objects.create(
                    fee_type=fee_type,
                    class_obj_id=class_id,
                )