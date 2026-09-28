from rest_framework import serializers

from .models import Class, ClassTeacher, ClassStudent
from apps.staffs.models import Staff
from apps.students.models import Student
from apps.academic_years.models import AcademicYear
from apps.academic_years.serializers import AcademicYearSerializer
from apps.staffs.serializers import StaffSerializer


class ClassStudentDetailSerializer(serializers.ModelSerializer):
    """Serializer for ClassStudent join table with nested student details"""
    
    student = serializers.SerializerMethodField()
    
    class Meta:
        model = ClassStudent
        fields = [
            "id",
            "student",
            "is_current",
            "created_at",
        ]
        read_only_fields = fields

    def get_student(self, obj):
        """Return full student details"""
        student = obj.student
        return {
            "id": student.id,
            "first_name": student.first_name,
            "last_name": student.last_name,
            "status": student.status,
            "date_of_birth": student.date_of_birth,
            "gender": student.gender,
            "nickname": student.nickname,
            "location_id": student.location_id,
            "enroll_date": student.enroll_date,
        }


class ClassTeacherDetailSerializer(serializers.ModelSerializer):
    """Serializer for ClassTeacher with nested staff details"""
    
    staff = StaffSerializer(read_only=True)
    
    class Meta:
        model = ClassTeacher
        fields = [
            "id",
            "staff",
            "created_at",
        ]
        read_only_fields = fields


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


class ClassDetailSerializer(serializers.ModelSerializer):
    """Enhanced serializer for Class detail, create, and update with full nested relations"""
    
    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
    )

    academic_year = serializers.PrimaryKeyRelatedField(
        queryset=AcademicYear.objects.all(),
    )
    
    class_teachers = ClassTeacherDetailSerializer(
        many=True,
        read_only=True,
    )
    
    class_students = ClassStudentDetailSerializer(
        many=True,
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
            "class_teachers",
            "class_students",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "branch_name",
            "class_teachers",
            "class_students",
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

    academic_year = serializers.PrimaryKeyRelatedField(
        source="class_obj.academic_year",
        queryset=Class.objects.all(),
    )

    academic_year_name = serializers.CharField(
        source="class_obj.academic_year.name",
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
            "academic_year",
            "academic_year_name",
        ]

        read_only_fields = [
            "id",
            "class_name",
            "teacher_name",
            "staff_type",
            "academic_year_name",
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