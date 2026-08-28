from rest_framework import serializers

from .models import StudentInvoice
from apps.classes.models import ClassStudent


class StudentInvoiceSerializer(serializers.ModelSerializer):

    class_student_id = serializers.PrimaryKeyRelatedField(
        source="class_student",
        queryset=ClassStudent.objects.select_related(
            "student",
            "class_obj",
        ),
    )

    student_name = serializers.SerializerMethodField()

    class_name = serializers.CharField(
        source="class_student.class_obj.name",
        read_only=True,
    )

    remaining_amount = serializers.SerializerMethodField()

    class Meta:
        model = StudentInvoice

        fields = [
            "id",
            "class_student_id",
            "student_name",
            "class_name",
            "fee_type",
            "invoice_no",
            "invoice_date",
            "due_date",
            "status",
            "tax_amount",
            "subtotal",
            "total_amount",
            "currency",
            "total_discount",
            "amount_paid",
            "remaining_amount",
            "remark",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "student_name",
            "class_name",
            "remaining_amount",
            "status",
            "created_at",
            "updated_at",
        ]

    def get_student_name(self, obj):
        student = obj.class_student.student

        return (
            f"{student.first_name} "
            f"{student.last_name}"
        ).strip()

    def get_remaining_amount(self, obj):
        return (
            obj.total_amount
            - obj.total_discount
            - obj.amount_paid
        )