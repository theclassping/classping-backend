from rest_framework import serializers

from apps.classes.models import Class, ClassTeacher
from apps.students.models import Student
from .models import Activity, ActivityImage, ActivityStudent


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


class ActivitySerializer(serializers.ModelSerializer):
    class_teacher_id = serializers.PrimaryKeyRelatedField(
        source="class_teacher",
        queryset=ClassTeacher.objects.all(),
    )

    class_id = serializers.PrimaryKeyRelatedField(
        source="class_obj",
        queryset=Class.objects.all(),
    )

    class_name = serializers.CharField(
        source="class_obj.name",
        read_only=True,
    )

    images = ActivityImageNestedSerializer(
        many=True,
        required=False,
    )

    activity_students = ActivityStudentNestedSerializer(
        many=True,
        required=False,
    )

    class Meta:
        model = Activity
        fields = [
            "id",
            "class_teacher_id",
            "class_id",
            "class_name",
            "name",
            "description",
            "activity_date",
            "images",
            "activity_students",
        ]
        read_only_fields = [
            "id",
            "class_name",
        ]

    def create(self, validated_data):
        images_data = validated_data.pop("images", [])
        activity_students_data = validated_data.pop("activity_students", [])

        activity = Activity.objects.create(**validated_data)

        self._sync_images(activity, images_data)
        self._sync_activity_students(activity, activity_students_data)

        return activity

    def update(self, instance, validated_data):
        images_data = validated_data.pop("images", None)
        activity_students_data = validated_data.pop("activity_students", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if images_data is not None:
            instance.images.all().delete()
            self._sync_images(instance, images_data)

        if activity_students_data is not None:
            instance.activity_students.all().delete()
            self._sync_activity_students(instance, activity_students_data)

        return instance

    def _sync_images(self, activity, images_data):
        for image_data in images_data:
            ActivityImage.objects.create(activity=activity, **image_data)

    def _sync_activity_students(self, activity, activity_students_data):
        for item in activity_students_data:
            ActivityStudent.objects.create(activity=activity, **item)


