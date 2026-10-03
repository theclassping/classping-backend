from rest_framework import permissions, viewsets
from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.users.permissions import RoleBasedAccessPermission

from .models import Class, ClassTeacher, ClassStudent
from .serializers import ClassSerializer, ClassDetailSerializer, ClassTeacherSerializer, ClassStudentSerializer


class ClassViewSet(viewsets.ModelViewSet):
    queryset = Class.objects.select_related(
        "branch",
        "academic_year",
    ).prefetch_related(
        "class_students__student",
        "class_teachers__staff",
    ).all()

    serializer_class = ClassSerializer

    permission_classes = [
        RoleBasedAccessPermission
    ]
    
    def get_serializer_class(self):
        """Use ClassDetailSerializer for detail, create, and update actions"""
        if self.action in ["retrieve", "create", "update", "partial_update"]:
            return ClassDetailSerializer
        return ClassSerializer

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
        RoleBasedAccessPermission
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        class_id = self.request.query_params.get("class_id")
        staff_id = self.request.query_params.get("staff_id")
        search = self.request.query_params.get("search") or self.request.query_params.get("q")
        if class_id:
            queryset = queryset.filter(class_obj_id=class_id)
        if staff_id:
            queryset = queryset.filter(staff_id=staff_id)
        if search:
            queryset = queryset.filter(Q(class_obj__name__icontains=search) | Q(staff__first_name__icontains=search) | Q(staff__last_name__icontains=search))
        return queryset

class ClassStudentViewSet(viewsets.ModelViewSet):
    queryset = ClassStudent.objects.select_related(
        "class_obj",
        "student",
    ).all()

    serializer_class = ClassStudentSerializer

    permission_classes = [
        RoleBasedAccessPermission
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        class_id = self.request.query_params.get("class_id")
        student_id = self.request.query_params.get("student_id")
        if class_id:
            queryset = queryset.filter(class_obj_id=class_id)
        if student_id:
            queryset = queryset.filter(student_id=student_id)
        return queryset
