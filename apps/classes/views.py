from rest_framework import permissions, viewsets

from .models import Class, ClassTeacher
from .serializers import ClassSerializer, ClassTeacherSerializer


class ClassViewSet(viewsets.ModelViewSet):
    queryset = Class.objects.select_related(
        "branch",
        "academic_year",
    ).all()

    serializer_class = ClassSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]

class ClassTeacherViewSet(viewsets.ModelViewSet):
    queryset = ClassTeacher.objects.select_related(
        "class_obj",
        "staff",
    ).all()

    serializer_class = ClassTeacherSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]