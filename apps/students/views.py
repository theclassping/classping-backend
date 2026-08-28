from rest_framework import viewsets

from .models import Student, StudentGuardian
from .serializers import StudentSerializer, StudentGuardianSerializer


class StudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.all().order_by("-id")
    serializer_class = StudentSerializer

class StudentGuardianViewSet(viewsets.ModelViewSet):
    queryset = StudentGuardian.objects.select_related(
        "student",
        "guardian",
    ).all()

    serializer_class = StudentGuardianSerializer