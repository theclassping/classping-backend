from rest_framework import serializers

from .models import AcademicYear
from apps.schools.models import Branch


class AcademicYearSerializer(serializers.ModelSerializer):

    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(),
        required=True,
    )

    class Meta:
        model = AcademicYear

        fields = [
            "id",
            "name",
            "branch",
            "start_date",
            "end_date",
            "is_current",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]
