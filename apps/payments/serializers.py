from rest_framework import serializers
from django.utils import timezone

from apps.student_invoices.models import StudentInvoice
from apps.uploads.paths import check_media_location
from apps.uploads.services.media import MediaService
from apps.uploads.serializers import resolve_image_input
from apps.mailer.services import Mailer
from django.conf import settings
from django.utils import timezone

from .models import Payment, PaymentProof


class PaymentProofSerializer(serializers.ModelSerializer):

    image_url = serializers.SerializerMethodField()

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
            "image_url",
            "uploaded_at",
        ]
        read_only_fields = [
            "id",
            "uploaded_at",
            "image_url",
        ]

    def get_image_url(self, obj):
        if not obj.image_data:
            return None

        object_key = obj.image_data.get("id") or obj.image_data.get("object_key")
        if not object_key:
            return None

        try:
            return MediaService.generate_download_url(object_key, expires_in=3600)
        except Exception:
            return None

    def validate_image_data(self, value):
        # A metadata dict gets the same checks as a file_key: it must be this
        # user's pending upload or an image they can already see.
        return resolve_image_input(self, value, as_field=False)


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
        payment = Payment(**validated_data)
        proofs = [
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
        # bulk_create skips the media signals, so check each key here,
        # before anything is written.
        for proof in proofs:
            key = (proof.image_data or {}).get("id") or (proof.image_data or {}).get("object_key")
            if key:
                check_media_location(proof, key)
        payment.save(force_insert=True)
        PaymentProof.objects.bulk_create(proofs)

        self._send_status_email(payment)

        return payment

    def update(self, instance, validated_data):
        new_status = validated_data.get("status")

        if new_status in (
            Payment.Status.COMPLETED,
            Payment.Status.REJECTED,
        ):
            # Staff verification is temporarily bypassed by the view. Keep
            # this safe for users (such as admins) without a Staff profile.
            staff = getattr(self.context["request"].user, "staff", None)
            instance.status = new_status
            instance.verified_at = timezone.now()
            instance.verified_by = staff

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
        guardian_assignment = student.student_guardians.filter(is_primary=True).select_related("guardian__user").first()
        if not guardian_assignment:
            return

        guardian = guardian_assignment.guardian
        recipient_name = guardian.name or guardian.user.full_name

        Mailer().send_template(
            to_email=guardian.user.email,
            to_name=recipient_name,
            template_id=template_id,
            variables={
                # Mail templates address the recipient as {{name}}.
                "name": recipient_name,
                "student_name": student.full_name(),
                "amount": str(payment.amount),
                "status": payment.status,
                "rejection_reason": payment.rejection_reason or "",
                "invoice_no": payment.student_invoice.invoice_no,
                "updated_at": (
                    timezone.localtime(payment.updated_at).strftime("%d %B %Y, %H:%M")
                    if payment.updated_at else ""
                ),
                "due_date": (
                    payment.student_invoice.due_date.strftime("%d %B %Y")
                    if payment.student_invoice.due_date else ""
                ),
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
        fields = PaymentSerializer.Meta.fields
