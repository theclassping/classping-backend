from rest_framework import permissions, serializers, status
from rest_framework import viewsets
from django.utils import timezone

from apps.student_invoices.models import StudentInvoice

from .models import Payment, PaymentProof
from .serializers import PaymentDetailSerializer, PaymentProofSerializer, PaymentSerializer


class PaymentViewSet(viewsets.ModelViewSet):

    queryset = Payment.objects.select_related(
        "student_invoice",
        "student_invoice__class_student",
        "student_invoice__class_student__student",
        "verified_by",
    ).prefetch_related(
        "proofs",
    ).all()

    serializer_class = PaymentSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        invoice_id = self.request.query_params.get("invoice_id")
        status_param = self.request.query_params.get("status")

        if invoice_id:
            queryset = queryset.filter(
                student_invoice_id=invoice_id
            )

        if status_param:
            queryset = queryset.filter(
                status=status_param
            )

        return queryset

    def perform_create(self, serializer):
        payment = serializer.save()
        invoice = payment.student_invoice
        invoice.status = StudentInvoice.Status.PAYMENT_SUBMITTED
        invoice.save(update_fields=["status", "updated_at"])

    def perform_update(self, serializer):
        payment = serializer.save()
        invoice = payment.student_invoice
        staff = getattr(self.request.user, "staff", None)

        if payment.status in [Payment.Status.COMPLETED, Payment.Status.REJECTED]:
            if not staff:
                raise permissions.PermissionDenied(
                    "Only staff members can verify or reject payments."
                )

            payment.verified_by_id = staff.id
            payment.verified_at = timezone.now()

            if payment.status == Payment.Status.COMPLETED:
                payment.paid_at = timezone.now()
                invoice.status = StudentInvoice.Status.PAID
                invoice.amount_paid = payment.amount
            else:
                invoice.status = StudentInvoice.Status.UNPAID

            payment.save()
            invoice.save(update_fields=["status", "amount_paid", "updated_at"])
            return payment

        if payment.status == Payment.Status.SUBMITTED and invoice.status != StudentInvoice.Status.PAYMENT_SUBMITTED:
            invoice.status = StudentInvoice.Status.PAYMENT_SUBMITTED
            invoice.save(update_fields=["status", "updated_at"])

        return payment

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PaymentDetailSerializer
        return PaymentSerializer


class PaymentProofViewSet(viewsets.ModelViewSet):

    queryset = PaymentProof.objects.select_related(
        "payment",
        "payment__student_invoice",
    ).all()
    serializer_class = PaymentProofSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        if not serializer.validated_data.get("payment"):
            raise serializers.ValidationError({
                "payment_id": "This field is required."
            })

        proof = serializer.save()
        payment = proof.payment

        if payment.status == Payment.Status.REJECTED:
            payment.status = Payment.Status.SUBMITTED
            payment.rejection_reason = None
            payment.verified_by = None
            payment.verified_at = None
            payment.save(
                update_fields=[
                    "status",
                    "rejection_reason",
                    "verified_by",
                    "verified_at",
                    "updated_at",
                ]
            )

            invoice = payment.student_invoice
            invoice.status = StudentInvoice.Status.PAYMENT_SUBMITTED
            invoice.save(update_fields=["status", "updated_at"])