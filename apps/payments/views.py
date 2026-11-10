from apps.core.access import ScopedQuerysetMixin
from rest_framework import permissions, serializers, status
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from django.utils import timezone
from django.db.models import Q
from django.db import transaction

from apps.student_invoices.models import StudentInvoice
from apps.users.permissions import RoleBasedAccessPermission
from apps.users.models import User

from .models import Payment, PaymentProof
from .serializers import PaymentDetailSerializer, PaymentProofSerializer, PaymentSerializer
from .services import (
    ensure_payment_is_manual,
    lock_invoice_for_manual_payment,
)

class PaymentViewSet(ScopedQuerysetMixin, viewsets.ModelViewSet):

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
        RoleBasedAccessPermission
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        invoice_id = (
            self.request.query_params.get("student_invoice_id")
            or self.request.query_params.get("invoice_id")
        )
        status_param = self.request.query_params.get("status")
        search = self.request.query_params.get("search") or self.request.query_params.get("q")

        if invoice_id:
            queryset = queryset.filter(
                student_invoice_id=invoice_id
            )

        if status_param:
            queryset = queryset.filter(
                status=status_param
            )
        if search:
            queryset = queryset.filter(Q(student_invoice__invoice_no__icontains=search) | Q(student_invoice__class_student__student__first_name__icontains=search) | Q(student_invoice__class_student__student__last_name__icontains=search))

        return queryset

    def perform_create(self, serializer):
        requested_status = serializer.validated_data.get(
            "status", Payment.Status.SUBMITTED
        )
        staff = getattr(self.request.user, "staff", None)
        if (
            requested_status in [Payment.Status.COMPLETED, Payment.Status.REJECTED]
            and not self._can_verify_payment(staff)
        ):
            raise PermissionDenied(
                "Only staff members can verify or reject payments."
            )

        with transaction.atomic():
            invoice = serializer.validated_data["student_invoice"]
            lock_invoice_for_manual_payment(invoice)
            payment = serializer.save()
            self._sync_payment_invoice(payment, staff)

    def perform_update(self, serializer):
        payment = serializer.instance
        ensure_payment_is_manual(payment)
        new_status = serializer.validated_data.get("status")
        staff = getattr(self.request.user, "staff", None)

        if (
            new_status in [Payment.Status.COMPLETED, Payment.Status.REJECTED]
            and not self._can_verify_payment(staff)
        ):
            raise PermissionDenied(
                "Only staff members can verify or reject payments."
            )

        with transaction.atomic():
            invoice = serializer.validated_data.get("student_invoice", payment.student_invoice)
            # Rejecting is always safe; anything else (re-submit, complete,
            # move to another invoice) must not race a gateway checkout.
            if (new_status or payment.status) != Payment.Status.REJECTED:
                lock_invoice_for_manual_payment(invoice)
            payment = serializer.save()
            self._sync_payment_invoice(payment, staff)
        return payment

    def perform_destroy(self, instance):
        ensure_payment_is_manual(instance)
        super().perform_destroy(instance)

    def _can_verify_payment(self, staff):
        return (
            self.request.user.is_superuser
            or str(self.request.user.role).lower() == User.Role.ADMIN.lower()
            or staff is not None
        )

    def _sync_payment_invoice(self, payment, staff):
        """Keep payment verification fields and invoice billing fields aligned."""
        invoice = payment.student_invoice
        payment_update_fields = ["updated_at"]
        invoice_update_fields = ["status", "amount_paid", "updated_at"]

        if payment.status == Payment.Status.COMPLETED:
            now = timezone.now()
            payment.paid_at = payment.paid_at or now
            payment.verified_at = payment.verified_at or now
            payment.verified_by = staff or payment.verified_by
            payment.rejection_reason = None
            invoice.status = StudentInvoice.Status.PAID
            invoice.amount_paid = payment.amount
            payment_update_fields.extend([
                "paid_at", "verified_at", "verified_by", "rejection_reason"
            ])
        elif payment.status == Payment.Status.REJECTED:
            payment.paid_at = None
            payment.verified_at = payment.verified_at or timezone.now()
            payment.verified_by = staff or payment.verified_by
            invoice.status = StudentInvoice.Status.UNPAID
            invoice.amount_paid = 0
            payment_update_fields.extend([
                "paid_at", "verified_at", "verified_by"
            ])
        else:
            payment.paid_at = None
            payment.verified_at = None
            payment.verified_by = None
            payment.rejection_reason = None
            invoice.status = StudentInvoice.Status.PAYMENT_SUBMITTED
            invoice.amount_paid = 0
            payment_update_fields.extend([
                "paid_at", "verified_at", "verified_by", "rejection_reason"
            ])

        payment.save(update_fields=payment_update_fields)
        invoice.save(update_fields=invoice_update_fields)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PaymentDetailSerializer
        return PaymentSerializer


class PaymentProofViewSet(ScopedQuerysetMixin, viewsets.ModelViewSet):

    queryset = PaymentProof.objects.select_related(
        "payment",
        "payment__student_invoice",
    ).all()
    serializer_class = PaymentProofSerializer
    permission_classes = [RoleBasedAccessPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        payment_id = self.request.query_params.get("payment_id")
        if payment_id:
            queryset = queryset.filter(payment_id=payment_id)
        return queryset

    def perform_create(self, serializer):
        if not serializer.validated_data.get("payment"):
            raise serializers.ValidationError({
                "payment_id": "This field is required."
            })

        with transaction.atomic():
            target = serializer.validated_data["payment"]
            ensure_payment_is_manual(target)
            if target.status == Payment.Status.REJECTED:
                # A proof re-submits a rejected payment (see below).
                lock_invoice_for_manual_payment(target.student_invoice_id)
            self._save_proof(serializer)

    def perform_update(self, serializer):
        ensure_payment_is_manual(serializer.instance.payment)
        target = serializer.validated_data.get("payment")
        if target is not None:
            ensure_payment_is_manual(target)
        serializer.save()

    def perform_destroy(self, instance):
        ensure_payment_is_manual(instance.payment)
        super().perform_destroy(instance)

    def _save_proof(self, serializer):
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
