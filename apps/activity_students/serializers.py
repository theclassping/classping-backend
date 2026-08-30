from rest_framework import serializers

from apps.activities.models import Activity
from apps.students.models import Student
from .models import ActivityStudent


class ActivityStudentSerializer(serializers.ModelSerializer):
    activity_id = serializers.PrimaryKeyRelatedField(
        source="activity",
        queryset=Activity.objects.all(),
    )

    student_id = serializers.PrimaryKeyRelatedField(
        source="student",
        queryset=Student.objects.all(),
    )

    student_name = serializers.SerializerMethodField()

    class Meta:
        model = ActivityStudent
        fields = [
            "id",
            "activity_id",
            "student_id",
            "student_name",
        ]
        read_only_fields = [
            "id",
            "student_name",
        ]

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}".strip()


class ActivityStudentNestedSerializer(serializers.ModelSerializer):
    # Excludes "activity_id" since it's assigned by the parent ActivitySerializer.
    student_id = serializers.PrimaryKeyRelatedField(
        source="student",
        queryset=Student.objects.all(),
    )

    student_name = serializers.SerializerMethodField()

    class Meta:
        model = ActivityStudent
        fields = [
            "id",
            "student_id",
            "student_name",
        ]
        read_only_fields = [
            "id",
            "student_name",
        ]

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}".strip()
