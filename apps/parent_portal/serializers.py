from rest_framework import serializers

from apps.classes.serializers import ClassDetailSerializer
from apps.schools.serializers import BranchSerializer, SchoolSerializer
from apps.students.serializers import StudentDetailSerializer, StudentSerializer


class ParentContextQuerySerializer(serializers.Serializer):
    student_id = serializers.IntegerField(required=False, min_value=1)


class ParentContextSerializer(serializers.Serializer):
    """Each part has the same shape as the existing endpoint noted beside it."""

    students = StudentSerializer(many=True, read_only=True)  # GET /api/students/
    student = StudentDetailSerializer(read_only=True, allow_null=True)  # GET /api/students/{id}/
    current_class = ClassDetailSerializer(read_only=True, allow_null=True)  # GET /api/classes/{id}/
    branch = BranchSerializer(read_only=True, allow_null=True)  # GET /api/branches/{id}/
    school = SchoolSerializer(read_only=True, allow_null=True)  # GET /api/schools/{id}/
