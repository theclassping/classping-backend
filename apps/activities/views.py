from rest_framework import viewsets
from django.db.models import Q

from .models import Activity, ActivityImage, ActivityStudent
from .serializers import (
    ActivitySerializer,
    ActivityImageSerializer,
    ActivityStudentSerializer,
)


class ActivityViewSet(viewsets.ModelViewSet):
    queryset = Activity.objects.select_related(
        "class_obj",
        "class_teacher",
    ).prefetch_related(
        "images",
        "activity_students__student",
    ).all()

    serializer_class = ActivitySerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search") or self.request.query_params.get("q")
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search) | Q(class_obj__name__icontains=search))
        class_id = self.request.query_params.get("class_id")
        student_id = self.request.query_params.get("student_id")
        is_publish = self.request.query_params.get("is_publish")
        if class_id:
            queryset = queryset.filter(class_obj_id=class_id)
        if student_id:
            queryset = queryset.filter(activity_students__student_id=student_id).distinct()
        if is_publish is not None:
            queryset = queryset.filter(is_publish=is_publish.lower() == "true")
        return queryset
    

class ActivityImageViewSet(viewsets.ModelViewSet):
    queryset = ActivityImage.objects.select_related(
        "activity",
        "student",
    ).all()

    serializer_class = ActivityImageSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        activity_id = self.request.query_params.get("activity_id")
        student_id = self.request.query_params.get("student_id")
        if activity_id: queryset = queryset.filter(activity_id=activity_id)
        if student_id: queryset = queryset.filter(student_id=student_id)
        return queryset


class ActivityStudentViewSet(viewsets.ModelViewSet):
    queryset = ActivityStudent.objects.select_related(
        "activity",
        "student",
    ).all()

    serializer_class = ActivityStudentSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        activity_id = self.request.query_params.get("activity_id")
        student_id = self.request.query_params.get("student_id")
        if activity_id: queryset = queryset.filter(activity_id=activity_id)
        if student_id: queryset = queryset.filter(student_id=student_id)
        return queryset
