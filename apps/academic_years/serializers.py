from rest_framework import serializers

from .models import AcademicYear


class AcademicYearSerializer(serializers.ModelSerializer):

    class Meta:
        model = AcademicYear

        fields = [
            "id",
            "name",
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