from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions
from rest_framework import viewsets

from .models import StudentInvoice
from .serializers import StudentInvoiceDetailSerializer, StudentInvoiceSerializer


class StudentInvoiceViewSet(viewsets.ModelViewSet):

    queryset = StudentInvoice.objects.select_related(
        "class_student",
        "class_student__student",
        "class_student__class_obj",
        "fee_type",
        "fee_type__branch",
        "fee_type_class",
        "fee_type_class__class_obj",
        "payment",
        "payment__verified_by",
    ).prefetch_related(
        "payment__proofs",
    ).all()

    serializer_class = StudentInvoiceSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return StudentInvoiceDetailSerializer
        return StudentInvoiceSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        student_id = self.request.query_params.get("student_id")
        status = self.request.query_params.get("status")
        fee_type_id = self.request.query_params.get("fee_type_id")
        payment_status = self.request.query_params.get("payment_status")
        is_overdue = self.request.query_params.get("is_overdue")

        if student_id:
            queryset = queryset.filter(
                class_student__student_id=student_id
            )

        if status:
            queryset = queryset.filter(
                status=status
            )

        if fee_type_id:
            queryset = queryset.filter(
                fee_type_id=fee_type_id
            )

        if payment_status:
            queryset = queryset.filter(
                payment__status=payment_status
            )

        if is_overdue is not None:
            today = timezone.now().date()
            is_overdue_flag = is_overdue.lower() == "true"

            if is_overdue_flag:
                queryset = queryset.exclude(
                    status=StudentInvoice.Status.PAID,
                ).filter(
                    due_date__lt=today,
                )
            else:
                queryset = queryset.filter(
                    Q(status=StudentInvoice.Status.PAID)
                    | Q(due_date__gte=today)
                )

        return queryset