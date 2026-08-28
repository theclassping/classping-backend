from rest_framework import serializers

from .models import StudentInvoice


class StudentInvoiceSerializer(serializers.ModelSerializer):

    fee_type_name = serializers.CharField(
        source="fee_type.name",
        read_only=True,
    )

    fee_type_amount = serializers.DecimalField(
        source="fee_type.amount",
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    student_id = serializers.IntegerField(
        source="class_student.student.id",
        read_only=True,
    )

    student_name = serializers.SerializerMethodField()

    class_name = serializers.CharField(
        source="class_student.class_obj.name",
        read_only=True,
    )

    class Meta:
        model = StudentInvoice

        fields = [
            "id",
            "invoice_no",

            "class_student",
            "student_id",
            "student_name",
            "class_name",

            "fee_type",
            "fee_type_name",
            "fee_type_amount",

            "invoice_date",
            "due_date",
            "status",

            "tax_amount",
            "subtotal",
            "total_amount",
            "currency",
            "total_discount",
            "amount_paid",

            "remark",

            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "student_id",
            "student_name",
            "class_name",
            "fee_type_name",
            "fee_type_amount",
            "created_at",
            "updated_at",
        ]

    def get_student_name(self, obj):
        student = obj.class_student.student

        return (
            f"{student.first_name} "
            f"{student.last_name}"
        ).strip()