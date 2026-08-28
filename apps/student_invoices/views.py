from rest_framework import permissions, viewsets

from .models import StudentInvoice
from .serializers import StudentInvoiceSerializer


class StudentInvoiceViewSet(viewsets.ModelViewSet):

    queryset = (
        StudentInvoice.objects
        .select_related(
            "class_student__student",
            "class_student__class_obj",
        )
        .all()
    )

    serializer_class = StudentInvoiceSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]