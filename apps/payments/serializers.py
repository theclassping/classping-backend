from rest_framework import serializers

from .models import Payment, PaymentProof


class PaymentProofSerializer(serializers.ModelSerializer):

    class Meta:
        model = PaymentProof
        fields = [
            "id",
            "payment",
            "image_data",
            "uploaded_at",
        ]
        read_only_fields = [
            "id",
            "uploaded_at",
        ]


class PaymentSerializer(serializers.ModelSerializer):

    invoice_no = serializers.CharField(
        source="student_invoice.invoice_no",
        read_only=True,
    )

    student_name = serializers.SerializerMethodField()

    verified_by_name = serializers.CharField(
        source="verified_by",
        read_only=True,
    )

    class Meta:
        model = Payment

        fields = [
            "id",
            "student_invoice",
            "invoice_no",
            "student_name",
            "amount",
            "payment_method",
            "status",
            "submitted_at",
            "paid_at",
            "verified_at",
            "verified_by",
            "verified_by_name",
            "rejection_reason",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "invoice_no",
            "student_name",
            "verified_by_name",
            "submitted_at",
            "paid_at",
            "verified_at",
            "created_at",
            "updated_at",
        ]

    def get_student_name(self, obj):
        student = obj.student_invoice.class_student.student
        return (
            f"{student.first_name} "
            f"{student.last_name}"
        ).strip()

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Amount must be greater than zero."
            )
        return value

    def validate(self, data):
        student_invoice = data.get("student_invoice")
        amount = data.get("amount")
        payment_status = data.get("status", self.instance.status if self.instance else None)
        rejection_reason = data.get(
            "rejection_reason",
            self.instance.rejection_reason if self.instance else None,
        )

        if student_invoice and amount and amount != student_invoice.total_amount:
            raise serializers.ValidationError(
                {
                    "amount": "Payment amount must match the invoice total."
                }
            )

        if payment_status == Payment.Status.REJECTED and not rejection_reason:
            raise serializers.ValidationError(
                {
                    "rejection_reason": "This field is required when rejecting a payment."
                }
            )

        return data


class PaymentSummarySerializer(serializers.ModelSerializer):

    class Meta:
        model = Payment
        fields = [
            "id",
            "amount",
            "payment_method",
            "status",
            "submitted_at",
            "paid_at",
            "verified_at",
            "rejection_reason",
        ]


class PaymentDetailSerializer(PaymentSerializer):

    proofs = PaymentProofSerializer(
        many=True,
        read_only=True,
    )

    class Meta(PaymentSerializer.Meta):
        fields = PaymentSerializer.Meta.fields + ["proofs"]