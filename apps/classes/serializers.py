from rest_framework import serializers

from .models import Class, ClassTeacher, ClassStudent
from apps.staffs.models import Staff
from apps.students.models import Student

class ClassSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
    )

    academic_year_name = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )

    class Meta:
        model = Class

        fields = [
            "id",
            "name",
            "branch",
            "branch_name",
            "academic_year",
            "academic_year_name",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "branch_name",
            "academic_year_name",
            "created_at",
            "updated_at",
        ]

class ClassTeacherSerializer(serializers.ModelSerializer):
    class_id = serializers.PrimaryKeyRelatedField(
        source="class_obj",
        queryset=Class.objects.all(),
    )

    staff_id = serializers.PrimaryKeyRelatedField(
        source="staff",
        queryset=Staff.objects.all(),
    )
    class_name = serializers.CharField(
        source="class_obj.name",
        read_only=True,
    )

    teacher_name = serializers.SerializerMethodField()

    staff_type = serializers.CharField(
        source="staff.staff_type",
        read_only=True,
    )

    class Meta:
        model = ClassTeacher

        fields = [
            "id",
            "class_id",
            "class_name",
            "staff_id",
            "teacher_name",
            "staff_type",
            "created_at",
        ]

        read_only_fields = [
            "id",
            "class_name",
            "teacher_name",
            "staff_type",
            "created_at",
        ]

    def get_teacher_name(self, obj):
        return f"{obj.staff.first_name} {obj.staff.last_name}".strip()

    def validate_staff(self, staff):
        if staff.staff_type != staff.StaffType.TEACHER:
            raise serializers.ValidationError(
                "Only staff with teacher type can be assigned to a class."
            )

        return staff
    
class ClassStudentSerializer(serializers.ModelSerializer):
    class_id = serializers.PrimaryKeyRelatedField(
        source="class_obj",
        queryset=Class.objects.all(),
    )

    student_id = serializers.PrimaryKeyRelatedField(
        source="student",
        queryset=Student.objects.all(),
    )
    class_name = serializers.CharField(
        source="class_obj.name",
        read_only=True,
    )

    student_name = serializers.SerializerMethodField()


    class Meta:
        model = ClassStudent

        fields = [
            "id",
            "class_id",
            "class_name",
            "student_id",
            "student_name",
            "created_at",
        ]

        read_only_fields = [
            "id",
            "class_name",
            "student_name",
            "created_at",
        ]

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}".strip()