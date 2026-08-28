from rest_framework import serializers
from .models import Student, StudentGuardian


class StudentSerializer(serializers.ModelSerializer):

    class Meta:
        model = Student
        fields = [
            "id",
            "first_name",
            "middle_name",
            "last_name",
            "nickname",
            "date_of_birth",
            "image_data",
            "gender",
            "address",
            "location_id",
            "enroll_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

class StudentGuardianSerializer(serializers.ModelSerializer):

    class Meta:
        model = StudentGuardian

        fields = [
            "id",
            "student",
            "guardian",
            "relationship",
            "is_primary",
        ]

        read_only_fields = [
            "id",
        ]