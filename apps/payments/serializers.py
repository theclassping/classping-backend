from rest_framework import serializers
from django.utils import timezone

from apps.student_invoices.models import StudentInvoice
from apps.uploads.services.media import MediaService
from apps.mailer.services import Mailer
from django.conf import settings

from .models import Payment, PaymentProof


class PaymentProofSerializer(serializers.ModelSerializer):

    payment_id = serializers.PrimaryKeyRelatedField(
        source="payment",
        queryset=Payment.objects.all(),
        required=False,
    )

    class Meta:
        model = PaymentProof
        fields = [
            "id",
            "payment_id",
            "image_data",
            "uploaded_at",
        ]
        read_only_fields = [
            "id",
            "uploaded_at",
        ]

    def validate_image_data(self, value):
        if isinstance(value, str):
            try:
                return MediaService.process_image_data(value)
            except FileNotFoundError:
                raise serializers.ValidationError(
                    "File not found. Provide a valid full file path or R2 URL."
                )
            except Exception as error:
                raise serializers.ValidationError(
                    f"Error processing image: {error}"
                )

        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "image_data must be a file path string or media metadata object."
            )

        return value


class PaymentSerializer(serializers.ModelSerializer):

    student_invoice_id = serializers.PrimaryKeyRelatedField(
        source="student_invoice",
        queryset=StudentInvoice.objects.all(),
    )

    verified_by_id = serializers.PrimaryKeyRelatedField(
        source="verified_by",
        read_only=True,
    )

    verified_by = serializers.SerializerMethodField()

    proofs = PaymentProofSerializer(
        many=True,
        required=False,
        write_only=True,
    )

    invoice_no = serializers.CharField(
        source="student_invoice.invoice_no",
        read_only=True,
    )

    student_name = serializers.SerializerMethodField()

    class Meta:
        model = Payment

        fields = [
            "id",
            "student_invoice_id",
            "invoice_no",
            "student_name",
            "amount",
            "payment_method",
            "status",
            "submitted_at",
            "paid_at",
            "verified_at",
            "verified_by_id",
            "verified_by",
            "rejection_reason",
            "proofs",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "invoice_no",
            "student_name",
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

    def get_verified_by(self, obj):
        staff = obj.verified_by
        if not staff:
            return None
        return {
            "id": staff.id,
            "first_name": staff.first_name,
            "last_name": staff.last_name,
            "email": staff.email
        }

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

    def create(self, validated_data):
        proofs_data = validated_data.pop("proofs", [])
        payment = Payment.objects.create(**{**validated_data, "paid_at": timezone.now()})
        PaymentProof.objects.bulk_create(
            [
                PaymentProof(
                    payment=payment,
                    **{
                        key: value
                        for key, value in proof_data.items()
                        if key != "payment"
                    },
                )
                for proof_data in proofs_data
            ]
        )

        self._send_status_email(payment)

        return payment

    def update(self, instance, validated_data):
        new_status = validated_data.get("status")

        if new_status in (
            Payment.Status.COMPLETED,
            Payment.Status.REJECTED,
        ):
            instance.status = new_status
            instance.verified_at = timezone.now()
            instance.verified_by = self.context["request"].user.staff

            if new_status == Payment.Status.REJECTED:
                instance.rejection_reason = validated_data.get(
                    "rejection_reason"
                )
            else:
                instance.rejection_reason = None

        else:
            for attr, value in validated_data.items():
                setattr(instance, attr, value)

        instance.save()
        self._send_status_email(instance)

        return instance

    def _send_status_email(self, payment):
        template_key = {
            Payment.Status.SUBMITTED: "payment_submitted",
            Payment.Status.COMPLETED: "payment_completed",
            Payment.Status.REJECTED: "payment_rejected",
        }.get(payment.status)

        if not template_key:
            return

        template_id = settings.MAILJET_TEMPLATES[template_key]
        student = payment.student_invoice.class_student.student
        guardian = student.student_guardians.filter(is_primary=True).first().guardian

        Mailer().send_template(
            to_email="raniaakhmalia@gmail.com",
            to_name=guardian.user.full_name,
            template_id=template_id,
            variables={
                "student_name": student.full_name(),
                "amount": str(payment.amount),
                "status": payment.status,
                "rejection_reason": payment.rejection_reason or "",
            },
        )

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