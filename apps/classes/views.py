from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Class, ClassTeacher, ClassStudent
from .serializers import ClassSerializer, ClassTeacherSerializer, ClassStudentSerializer


class ClassViewSet(viewsets.ModelViewSet):
    queryset = Class.objects.select_related(
        "branch",
        "academic_year",
    ).all()

    serializer_class = ClassSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]

    @action(
        detail=True,
        methods=["get"],
        url_path="students",
    )
    def students(self, request, pk=None):
        class_obj = self.get_object()

        assignments = (
            ClassStudent.objects
            .filter(class_obj=class_obj)
            .select_related("student")
        )

        serializer = ClassStudentSerializer(
            assignments,
            many=True,
        )

        return Response(serializer.data)

    @action(
        detail=True,
        methods=["get"],
        url_path="teachers",
    )
    def teachers(self, request, pk=None):
        class_obj = self.get_object()

        assignments = (
            ClassTeacher.objects
            .filter(class_obj=class_obj)
            .select_related("staff")
        )

        serializer = ClassTeacherSerializer(
            assignments,
            many=True,
        )

        return Response(serializer.data)

class ClassTeacherViewSet(viewsets.ModelViewSet):
    queryset = ClassTeacher.objects.select_related(
        "class_obj",
        "staff",
    ).all()

    serializer_class = ClassTeacherSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]

class ClassStudentViewSet(viewsets.ModelViewSet):
    queryset = ClassStudent.objects.select_related(
        "class_obj",
        "student",
    ).all()

    serializer_class = ClassStudentSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]