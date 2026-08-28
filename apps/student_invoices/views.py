from rest_framework import permissions
from rest_framework import viewsets

from .models import StudentInvoice
from .serializers import StudentInvoiceSerializer


class StudentInvoiceViewSet(viewsets.ModelViewSet):

    queryset = StudentInvoice.objects.select_related(
        "class_student",
        "class_student__student",
        "class_student__class_obj",
        "fee_type",
        "fee_type__branch",
    ).all()

    serializer_class = StudentInvoiceSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        student_id = self.request.query_params.get("student_id")
        status = self.request.query_params.get("status")
        fee_type_id = self.request.query_params.get("fee_type_id")

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

        return queryset