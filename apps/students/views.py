from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Student, StudentGuardian
from .serializers import (
    StudentSerializer,
    StudentDetailSerializer,
    StudentGuardianSerializer,
)
from apps.student_invoices.models import StudentInvoice
from apps.student_invoices.serializers import StudentInvoiceSerializer


class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.all().order_by("-id")
    serializer_class = StudentSerializer

    def get_serializer_class(self):
        if self.action == "retrieve":
            return StudentDetailSerializer

        return StudentSerializer

    @action(
        detail=True,
        methods=["get"],
        url_path="invoices",
    )
    def invoices(self, request, pk=None):

        invoices = (
            StudentInvoice.objects
            .filter(
                class_student__student_id=pk
            )
            .select_related(
                "class_student__student",
                "class_student__class_obj",
            )
        )

        # Filter by status
        status = request.query_params.get("status")

        if status:
            invoices = invoices.filter(
                status=status
            )

        serializer = StudentInvoiceSerializer(
            invoices,
            many=True,
        )

        return Response(serializer.data)   

class StudentGuardianViewSet(viewsets.ModelViewSet):
    queryset = StudentGuardian.objects.select_related(
        "student",
        "guardian",
    ).all()

    serializer_class = StudentGuardianSerializer 