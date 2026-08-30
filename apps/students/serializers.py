from rest_framework import serializers

from apps.classes.models import Class, ClassStudent
from apps.classes.serializers import ClassSerializer
from apps.guardians.models import Guardian
from apps.guardians.serializers import GuardianSerializer, GuardianInlineSerializer
from apps.locations.models import Location
from apps.locations.serializers import LocationSerializer
from .models import Student, StudentGuardian


class StudentGuardianNestedSerializer(serializers.ModelSerializer):
    # Excludes "student_id" since it's assigned by the parent StudentSerializer.
    # Provide either "guardian_id" (existing guardian id) or "user" (to create a new guardian + login user).
    guardian_id = serializers.PrimaryKeyRelatedField(
        source="guardian",
        queryset=Guardian.objects.all(),
        required=False,
    )

    user = GuardianInlineSerializer(
        required=False,
    )

    class Meta:
        model = StudentGuardian
        fields = [
            "id",
            "guardian_id",
            "user",
            "relationship",
            "is_primary",
        ]
        read_only_fields = [
            "id",
        ]

    def validate(self, attrs):
        if not attrs.get("guardian") and not attrs.get("user"):
            raise serializers.ValidationError(
                "Provide either 'guardian_id' (existing guardian id) or 'user' (to create one)."
            )
        return attrs


class StudentSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()

    student_guardians = StudentGuardianNestedSerializer(
        many=True,
        required=False,
    )

    class_ids = serializers.PrimaryKeyRelatedField(
        queryset=Class.objects.all(),
        many=True,
        required=False,
        write_only=True,
    )

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
            "location",
            "student_guardians",
            "class_ids",
            "enroll_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def get_location(self, obj):
        if not obj.location_id:
            return None

        location = Location.objects.filter(pk=obj.location_id).first()

        if not location:
            return None

        return LocationSerializer(location).data

    def create(self, validated_data):
        student_guardians_data = validated_data.pop("student_guardians", [])
        classes = validated_data.pop("class_ids", [])

        student = Student.objects.create(**validated_data)

        self._sync_student_guardians(student, student_guardians_data)
        self._sync_classes(student, classes)

        return student

    def update(self, instance, validated_data):
        student_guardians_data = validated_data.pop("student_guardians", None)
        classes = validated_data.pop("class_ids", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if student_guardians_data is not None:
            instance.student_guardians.all().delete()
            self._sync_student_guardians(instance, student_guardians_data)

        if classes is not None:
            instance.class_student_assignments.all().delete()
            self._sync_classes(instance, classes)

        return instance

    def _sync_student_guardians(self, student, student_guardians_data):
        for item in student_guardians_data:
            new_guardian_data = item.pop("user", None)
            guardian = item.pop("guardian", None)

            if new_guardian_data:
                guardian = GuardianInlineSerializer().create(new_guardian_data)

            StudentGuardian.objects.create(student=student, guardian=guardian, **item)

    def _sync_classes(self, student, classes):
        for class_obj in classes:
            ClassStudent.objects.create(student=student, class_obj=class_obj)


class StudentDetailSerializer(StudentSerializer):
    guardian = serializers.SerializerMethodField()
    classes = serializers.SerializerMethodField()

    class Meta(StudentSerializer.Meta):
        fields = StudentSerializer.Meta.fields + [
            "guardian",
            "classes",
        ]

    def get_guardian(self, obj):
        # Primary guardian if set, otherwise fall back to the first linked guardian.
        student_guardian = (
            obj.student_guardians
            .select_related("guardian")
            .order_by("-is_primary")
            .first()
        )

        if not student_guardian:
            return None

        data = GuardianSerializer(student_guardian.guardian).data
        data["relationship"] = student_guardian.relationship
        data["is_primary"] = student_guardian.is_primary
        return data

    def get_classes(self, obj):
        classes = Class.objects.filter(
            class_students__student=obj,
        ).select_related("branch", "academic_year")

        return ClassSerializer(classes, many=True).data


class StudentGuardianSerializer(serializers.ModelSerializer):
    student_id = serializers.PrimaryKeyRelatedField(
        source="student",
        queryset=Student.objects.all(),
    )

    guardian_id = serializers.PrimaryKeyRelatedField(
        source="guardian",
        queryset=Guardian.objects.all(),
    )

    class Meta:
        model = StudentGuardian

        fields = [
            "id",
            "student_id",
            "guardian_id",
            "relationship",
            "is_primary",
        ]

        read_only_fields = [
            "id",
        ]