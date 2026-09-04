from django.db import transaction

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
    #
    # - Omit "id": create a new link (via "guardian_id" existing, or "user" to create a guardian).
    # - Include "id": update that existing link's relationship/is_primary/guardian_id in place.
    # - Include "id" + "_destroy": true: remove that existing link.
    id = serializers.IntegerField(required=False)

    guardian_id = serializers.PrimaryKeyRelatedField(
        source="guardian",
        queryset=Guardian.objects.all(),
        required=False,
    )

    user = GuardianInlineSerializer(
        required=False,
    )

    relationship = serializers.ChoiceField(
        choices=StudentGuardian.RELATIONSHIP_CHOICES,
        required=False,
    )

    _destroy = serializers.BooleanField(
        required=False,
        default=False,
        write_only=True,
    )

    class Meta:
        model = StudentGuardian
        fields = [
            "id",
            "guardian_id",
            "user",
            "relationship",
            "is_primary",
            "_destroy",
        ]

    def validate(self, attrs):
        if attrs.get("_destroy"):
            if not attrs.get("id"):
                raise serializers.ValidationError(
                    "'_destroy' requires an existing 'id'."
                )
            return attrs

        if not attrs.get("id"):
            if not attrs.get("guardian") and not attrs.get("user"):
                raise serializers.ValidationError(
                    "Provide either 'guardian_id' (existing guardian id) or 'user' (to create one)."
                )

            if not attrs.get("relationship"):
                raise serializers.ValidationError(
                    "'relationship' is required when creating a new link."
                )

        return attrs


class StudentSerializer(serializers.ModelSerializer):

    location = serializers.SerializerMethodField()

    # Nested student guardians (write) - used in create/update
    student_guardians = StudentGuardianNestedSerializer(
        many=True,
        required=False,
    )

    # Write-only class IDs (set-diff sync)
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

    # ========================================================
    # LOCATION
    # ========================================================

    def get_location(self, obj):
        if not obj.location_id:
            return None

        location = Location.objects.filter(pk=obj.location_id).first()

        if not location:
            return None

        return LocationSerializer(location).data

    # ========================================================
    # VALIDATION
    # ========================================================

    def validate(self, attrs):
        """
        Validate student data:
        - Location exists if provided
        - Enrollment date is valid
        """

        location_id = attrs.get(
            "location_id",
            getattr(self.instance, "location_id", None),
        )

        if location_id:
            if not Location.objects.filter(pk=location_id).exists():
                raise serializers.ValidationError({
                    "location_id": "Location does not exist."
                })

        return attrs

    # ========================================================
    # CREATE
    # ========================================================

    @transaction.atomic
    def create(self, validated_data):
        """
        Create a new student with nested guardians and class assignments.
        """

        # Remove custom fields before Student.objects.create()
        student_guardians_data = validated_data.pop(
            "student_guardians",
            [],
        )

        classes = validated_data.pop(
            "class_ids",
            [],
        )

        # Create Student
        student = Student.objects.create(**validated_data)

        # Sync student guardians (create/update/delete)
        self._sync_student_guardians(
            student,
            student_guardians_data,
        )

        # Sync class assignments (set-diff)
        self._sync_classes(
            student,
            classes,
        )

        return student

    # ========================================================
    # UPDATE
    # ========================================================

    @transaction.atomic
    def update(self, instance, validated_data):
        """
        Update student with optional nested guardians and class assignments.

        If student_guardians is provided: sync (create/update/delete).
        If student_guardians is omitted: keep existing.

        If class_ids is provided: sync (replace with new list).
        If class_ids is omitted: keep existing.
        """

        # student_guardians:
        # If provided: process nested create/update/delete.
        # If not provided: keep existing guardians.
        student_guardians_data = validated_data.pop(
            "student_guardians",
            None,
        )

        # class_ids:
        # If provided: replace/sync class assignments.
        # If not provided: keep existing classes.
        classes = validated_data.pop(
            "class_ids",
            None,
        )

        # ------------------------------------------------
        # Update Student fields
        # ------------------------------------------------

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        # ------------------------------------------------
        # Sync student guardians
        # ------------------------------------------------

        if student_guardians_data is not None:
            self._sync_student_guardians(
                instance,
                student_guardians_data,
            )

        # ------------------------------------------------
        # Sync class assignments
        # ------------------------------------------------

        if classes is not None:
            self._sync_classes(
                instance,
                classes,
            )

        return instance

    # ========================================================
    # SYNC STUDENT GUARDIANS
    # ========================================================

    def _sync_student_guardians(self, student, student_guardians_data):
        """
        Rails-like accepts_nested_attributes_for behavior.

        Example:

        {
            "student_guardians": [
                {
                    "id": 10,
                    "relationship": "mother",
                    "is_primary": true
                },
                {
                    "id": 11,
                    "_destroy": true
                },
                {
                    "guardian_id": 5,
                    "relationship": "father"
                },
                {
                    "user": {
                        "email": "newguardian@example.com",
                        "first_name": "New",
                        "last_name": "Guardian"
                    },
                    "relationship": "grandfather"
                }
            ]
        }

        Result:

        ID 10 -> UPDATE
        ID 11 -> DELETE
        guardian_id 5 -> CREATE (link student to existing guardian)
        "user" -> CREATE (new guardian + student link)
        """

        for item in student_guardians_data:

            # Get existing link ID.
            # None means this is a new link.
            guardian_link_id = item.pop("id", None)

            # Get destroy flag.
            # Default is False.
            destroy = item.pop("_destroy", False)

            # Get inline guardian data (to create new guardian).
            new_guardian_data = item.pop("user", None)

            # Get guardian object (existing guardian).
            guardian = item.pop("guardian", None)

            # ------------------------------------------------
            # UPDATE OR DELETE EXISTING LINK
            # ------------------------------------------------

            if guardian_link_id:

                # Fetch existing link scoped to this student.
                link = student.student_guardians.filter(
                    pk=guardian_link_id
                ).first()

                if not link:
                    raise serializers.ValidationError({
                        "student_guardians": (
                            f"No existing link with "
                            f"id {guardian_link_id} "
                            f"for this student."
                        )
                    })

                # DELETE existing link
                if destroy:
                    link.delete()
                    continue

                # UPDATE existing link
                if guardian:
                    link.guardian = guardian

                for attr, value in item.items():
                    setattr(link, attr, value)

                link.save()
                continue

            # ------------------------------------------------
            # CREATE NEW LINK
            # ------------------------------------------------

            # Create new guardian if inline data provided.
            if new_guardian_data:
                guardian = GuardianInlineSerializer().create(
                    new_guardian_data
                )

            StudentGuardian.objects.create(
                student=student,
                guardian=guardian,
                **item,
            )

    # ========================================================
    # SYNC CLASSES
    # ========================================================

    def _sync_classes(self, student, classes):
        """
        Replace student class assignments using set-diff.

        Example:

        Current:
        [1, 2, 3]

        Incoming:
        [2, 3, 4]

        Result:
        [2, 3, 4]

        Class 1 -> removed from student
        Class 4 -> added to student

        The Class records themselves are NOT deleted.
        """

        current_class_ids = set(
            student.class_student_assignments.values_list(
                "class_obj_id",
                flat=True,
            )
        )

        incoming_class_ids = {
            class_obj.pk
            for class_obj in classes
        }

        # ------------------------------------------------
        # Remove classes
        # ------------------------------------------------

        class_ids_to_remove = (
            current_class_ids - incoming_class_ids
        )

        if class_ids_to_remove:
            student.class_student_assignments.filter(
                class_obj_id__in=class_ids_to_remove
            ).delete()

        # ------------------------------------------------
        # Add classes
        # ------------------------------------------------

        class_ids_to_add = (
            incoming_class_ids - current_class_ids
        )

        if class_ids_to_add:
            ClassStudent.objects.bulk_create([
                ClassStudent(
                    student=student,
                    class_obj_id=class_id,
                )
                for class_id in class_ids_to_add
            ])


class StudentGuardianDetailSerializer(serializers.ModelSerializer):
    guardian = GuardianSerializer(read_only=True)

    class Meta:
        model = StudentGuardian
        fields = [
            "id",
            "guardian",
            "relationship",
            "is_primary",
        ]


class StudentDetailSerializer(StudentSerializer):
    student_guardians = StudentGuardianDetailSerializer(
        many=True,
        read_only=True,
    )

    classes = serializers.SerializerMethodField()

    class Meta(StudentSerializer.Meta):
        fields = StudentSerializer.Meta.fields + [
            "classes",
        ]

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