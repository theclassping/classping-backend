from django.db import transaction

from rest_framework import serializers

from apps.classes.models import Class, ClassTeacher
from apps.students.models import Student

from .models import (
    Activity,
    ActivityImage,
    ActivityStudent,
)


# ============================================================
# STUDENT SUMMARY
# ============================================================

class ActivityStudentSummarySerializer(serializers.ModelSerializer):

    class Meta:
        model = Student

        fields = [
            "id",
            "first_name",
            "middle_name",
            "last_name",
            "nickname",
        ]


# ============================================================
# ACTIVITY IMAGE
# Standalone serializer for /activity-images/
# ============================================================

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
            "position",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]


# ============================================================
# NESTED ACTIVITY IMAGE
# Used inside ActivitySerializer
# ============================================================

class ActivityImageNestedSerializer(serializers.ModelSerializer):

    # Existing image ID.
    # If ID exists -> update/delete existing image.
    # If ID does not exist -> create new image.
    id = serializers.IntegerField(
        required=False,
    )

    student_id = serializers.PrimaryKeyRelatedField(
        source="student",
        queryset=Student.objects.all(),
        required=False,
        allow_null=True,
    )

    # Rails-like nested attributes destroy flag.
    _destroy = serializers.BooleanField(
        required=False,
        write_only=True,
    )

    class Meta:
        model = ActivityImage

        fields = [
            "id",
            "student_id",
            "image_data",
            "caption",
            "position",
            "_destroy",
        ]

        extra_kwargs = {
            "image_data": {
                "required": False,
            },
        }


# ============================================================
# ACTIVITY STUDENT
# Optional standalone serializer.
#
# You can remove this later if you no longer expose
# /activity-students/ as an API endpoint.
# ============================================================

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
            "created_at",
        ]

        read_only_fields = [
            "id",
            "student_name",
            "created_at",
        ]

    def get_student_name(self, obj):
        return (
            f"{obj.student.first_name} "
            f"{obj.student.last_name}"
        ).strip()


# ============================================================
# ACTIVITY
# ============================================================

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

    # Nested images
    images = ActivityImageNestedSerializer(
        many=True,
        required=False,
    )

    # Read-only student data
    students = ActivityStudentSummarySerializer(
        many=True,
        read_only=True,
    )

    # Write-only student IDs
    student_ids = serializers.PrimaryKeyRelatedField(
        queryset=Student.objects.all(),
        many=True,
        required=False,
        write_only=True,
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
            "students",
            "student_ids",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "class_name",
            "students",
            "created_at",
            "updated_at",
        ]

    # ========================================================
    # VALIDATION
    # ========================================================

    def validate(self, attrs):

        # Get new value if provided.
        # Otherwise use existing value during PATCH.
        class_teacher = attrs.get(
            "class_teacher",
            getattr(
                self.instance,
                "class_teacher",
                None,
            ),
        )

        class_obj = attrs.get(
            "class_obj",
            getattr(
                self.instance,
                "class_obj",
                None,
            ),
        )

        students = attrs.get(
            "student_ids",
            None,
        )

        images = attrs.get(
            "images",
            None,
        )

        # ----------------------------------------------------
        # Validate teacher belongs to class
        # ----------------------------------------------------

        if (
            class_teacher
            and class_obj
            and class_teacher.class_obj_id != class_obj.id
        ):
            raise serializers.ValidationError({
                "class_teacher_id": (
                    "The selected teacher must belong "
                    "to the selected class."
                )
            })

        # ----------------------------------------------------
        # Validate students belong to class
        # ----------------------------------------------------

        if students is not None and class_obj:

            class_student_ids = set(
                class_obj.class_students.values_list(
                    "student_id",
                    flat=True,
                )
            )

            invalid_student_ids = [
                student.id
                for student in students
                if student.id not in class_student_ids
            ]

            if invalid_student_ids:
                raise serializers.ValidationError({
                    "student_ids": (
                        "One or more students do not "
                        "belong to the selected class."
                    )
                })

        # ----------------------------------------------------
        # Validate existing images belong to activity
        # ----------------------------------------------------

        if (
            images is not None
            and self.instance is not None
        ):

            existing_image_ids = set(
                self.instance.images.values_list(
                    "id",
                    flat=True,
                )
            )

            for image_data in images:

                image_id = image_data.get(
                    "id",
                    None,
                )

                if (
                    image_id is not None
                    and image_id not in existing_image_ids
                ):
                    raise serializers.ValidationError({
                        "images": (
                            f"Image ID {image_id} does not "
                            "belong to this activity."
                        )
                    })

        return attrs

    # ========================================================
    # CREATE
    # ========================================================

    @transaction.atomic
    def create(self, validated_data):

        # Remove custom fields before Activity.objects.create()
        students = validated_data.pop(
            "student_ids",
            [],
        )

        images = validated_data.pop(
            "images",
            [],
        )

        # Create Activity
        activity = Activity.objects.create(
            **validated_data
        )

        # Create ActivityStudent relationships
        self._sync_students(
            activity,
            students,
        )

        # Create nested images
        self._sync_images(
            activity,
            images,
        )

        return activity

    # ========================================================
    # UPDATE
    # ========================================================

    @transaction.atomic
    def update(self, instance, validated_data):

        # student_ids:
        #
        # If provided:
        # replace/sync student relationships.
        #
        # If not provided:
        # keep existing students.
        students = validated_data.pop(
            "student_ids",
            None,
        )

        # images:
        #
        # If provided:
        # process nested create/update/delete.
        #
        # If not provided:
        # keep existing images.
        images = validated_data.pop(
            "images",
            None,
        )

        # ----------------------------------------------------
        # Update Activity fields
        # ----------------------------------------------------

        for attr, value in validated_data.items():
            setattr(
                instance,
                attr,
                value,
            )

        instance.save()

        # ----------------------------------------------------
        # Sync students
        # ----------------------------------------------------

        if students is not None:

            self._sync_students(
                instance,
                students,
            )

        # ----------------------------------------------------
        # Sync nested images
        # ----------------------------------------------------

        if images is not None:

            self._sync_images(
                instance,
                images,
            )

        return instance

    # ========================================================
    # SYNC STUDENTS
    # ========================================================

    def _sync_students(
        self,
        activity,
        students,
    ):
        """
        Replace ActivityStudent relationships.

        Example:

        Current:
        [1, 2, 3]

        Incoming:
        [2, 3, 4]

        Result:
        [2, 3, 4]

        Student 1 -> removed from activity
        Student 4 -> added to activity

        The Student records themselves are NOT deleted.
        """

        current_ids = set(
            activity.students.values_list(
                "id",
                flat=True,
            )
        )

        incoming_ids = {
            student.id
            for student in students
        }

        # ----------------------------------------------------
        # Remove students
        # ----------------------------------------------------

        student_ids_to_remove = (
            current_ids - incoming_ids
        )

        if student_ids_to_remove:

            activity.activity_students.filter(
                student_id__in=student_ids_to_remove
            ).delete()

        # ----------------------------------------------------
        # Add students
        # ----------------------------------------------------

        student_ids_to_add = (
            incoming_ids - current_ids
        )

        if student_ids_to_add:

            ActivityStudent.objects.bulk_create(
                [
                    ActivityStudent(
                        activity=activity,
                        student_id=student_id,
                    )
                    for student_id in student_ids_to_add
                ]
            )

    # ========================================================
    # SYNC IMAGES
    # ========================================================

    def _sync_images(
        self,
        activity,
        images,
    ):
        """
        Rails-like accepts_nested_attributes_for behavior.

        Example:

        {
            "images": [
                {
                    "id": 10,
                    "caption": "Updated caption"
                },
                {
                    "id": 11,
                    "_destroy": true
                },
                {
                    "student_id": 2,
                    "image_data": <file>,
                    "caption": "New image"
                }
            ]
        }

        Result:

        ID 10 -> UPDATE
        ID 11 -> DELETE
        No ID -> CREATE
        """

        existing_images = {
            image.id: image
            for image in activity.images.all()
        }

        for image_data in images:

            # Get existing image ID.
            # None means this is a new image.
            image_id = image_data.pop(
                "id",
                None,
            )

            # Get destroy flag.
            # Default is False.
            should_destroy = image_data.pop(
                "_destroy",
                False,
            )

            # ------------------------------------------------
            # CREATE NEW IMAGE
            # ------------------------------------------------

            if image_id is None:

                # Ignore if frontend sends:
                #
                # {
                #     "_destroy": true
                # }
                #
                # because there is no existing image to delete.

                if should_destroy:
                    continue

                ActivityImage.objects.create(
                    activity=activity,
                    **image_data,
                )

                continue

            # ------------------------------------------------
            # GET EXISTING IMAGE
            # ------------------------------------------------

            image = existing_images.get(
                image_id
            )

            # This should normally already be caught
            # in validate(), but keeping this is safer.
            if image is None:

                raise serializers.ValidationError({
                    "images": (
                        f"Image ID {image_id} does not "
                        "belong to this activity."
                    )
                })

            # ------------------------------------------------
            # DELETE EXISTING IMAGE
            # ------------------------------------------------

            if should_destroy:

                image.delete()

                continue

            # ------------------------------------------------
            # UPDATE EXISTING IMAGE
            # ------------------------------------------------

            for attr, value in image_data.items():

                setattr(
                    image,
                    attr,
                    value,
                )

            image.save()