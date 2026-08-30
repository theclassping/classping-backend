from rest_framework import serializers

from apps.activities.models import Activity
from apps.students.models import Student
from .models import ActivityImage


class ActivityImageSerializer(serializers.ModelSerializer):
    activity_id = serializers.PrimaryKeyRelatedField(
        source="activity",
        queryset=Activity.objects.all(),
    )

    student_id = serializers.PrimaryKeyRelatedField(
        source="student",
        queryset=Student.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = ActivityImage
        fields = [
            "id",
            "activity_id",
            "student_id",
            "image_data",
            "caption",
        ]
        read_only_fields = [
            "id",
        ]


class ActivityImageNestedSerializer(serializers.ModelSerializer):
    # Excludes "activity_id" since it's assigned by the parent ActivitySerializer.
    student_id = serializers.PrimaryKeyRelatedField(
        source="student",
        queryset=Student.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = ActivityImage
        fields = [
            "id",
            "student_id",
            "image_data",
            "caption",
        ]
        read_only_fields = [
            "id",
        ]
