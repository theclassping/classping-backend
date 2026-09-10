from django.utils import timezone
from rest_framework import serializers

from apps.fee_types.models import FeeType
from apps.payments.serializers import PaymentDetailSerializer, PaymentSummarySerializer

from .models import StudentInvoice


class FeeTypeMiniSerializer(serializers.ModelSerializer):

    class Meta:
        model = FeeType
        fields = [
            "id",
            "name",
            "description",
            "amount",
            "currency",
            "is_recurring",
            "recurring_frequency",
            "is_active",
        ]


class StudentInvoiceSerializer(serializers.ModelSerializer):

    fee_type = FeeTypeMiniSerializer(read_only=True)

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

    fee_type_class_name = serializers.CharField(
        source="fee_type_class.class_obj.name",
        read_only=True,
        default=None,
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

    payment = PaymentSummarySerializer(read_only=True)

    is_overdue = serializers.SerializerMethodField()

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

            "fee_type_class",
            "fee_type_class_name",

            "invoice_date",
            "due_date",
            "status",
            "is_overdue",

            "tax_amount",
            "subtotal",
            "total_amount",
            "currency",
            "total_discount",
            "amount_paid",

            "payment",

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
            "fee_type_class_name",
            "is_overdue",
            "created_at",
            "updated_at",
        ]

    def get_student_name(self, obj):
        student = obj.class_student.student

        return (
            f"{student.first_name} "
            f"{student.last_name}"
        ).strip()

    def get_is_overdue(self, obj):
        return (
            obj.status != StudentInvoice.Status.PAID
            and obj.due_date < timezone.now().date()
        )


class StudentInvoiceDetailSerializer(StudentInvoiceSerializer):

    payment = PaymentDetailSerializer(read_only=True)