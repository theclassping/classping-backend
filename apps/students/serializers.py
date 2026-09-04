from django.db import transaction
from django.contrib.auth import get_user_model

from rest_framework import serializers

from apps.classes.models import Class, ClassStudent
from apps.classes.serializers import ClassSerializer
from apps.guardians.models import Guardian
from apps.guardians.serializers import GuardianSerializer, GuardianInlineSerializer
from apps.locations.models import Location
from apps.locations.serializers import LocationSerializer
from .models import Student, StudentGuardian

User = get_user_model()


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


class ClassStudentNestedSerializer(serializers.ModelSerializer):
    """
    Nested serializer for class_students.
    
    - Omit "id": create new assignment (class_id required).
    - Include "id": update is_current or other fields.
    - Include "id" + "_destroy": true: remove assignment.
    """

    id = serializers.IntegerField(required=False)

    class_id = serializers.PrimaryKeyRelatedField(
        source="class_obj",
        queryset=Class.objects.all(),
        required=False,
    )

    is_current = serializers.BooleanField(
        required=False,
        default=False,
    )

    _destroy = serializers.BooleanField(
        required=False,
        default=False,
        write_only=True,
    )

    class Meta:
        model = ClassStudent
        fields = [
            "id",
            "class_id",
            "is_current",
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
            if not attrs.get("class_obj"):
                raise serializers.ValidationError(
                    "'class_id' is required when creating a new class assignment."
                )

        return attrs


class StudentSerializer(serializers.ModelSerializer):

    location = serializers.SerializerMethodField()

    # Nested student guardians (write-only - input only for create/update)
    student_guardians = StudentGuardianNestedSerializer(
        many=True,
        required=False,
        write_only=True,
    )

    # Nested class_students (write-only - input only for create/update)
    class_students = ClassStudentNestedSerializer(
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
            "status",
            "student_guardians",
            "class_students",
            "enroll_date",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        """
        Customize response serialization to include class_students and student_guardians.
        Since nested serializers are write_only, they don't appear in response.
        This method manually adds them back for the response.
        """
        # Call parent which won't include write_only fields
        data = super().to_representation(instance)
        
        # Add student_guardians as simple nested data (read response)
        if instance and instance.pk:
            student_guardians_data = []
            for sg in instance.student_guardians.select_related("guardian").all():
                student_guardians_data.append({
                    "id": sg.id,
                    "guardian_id": sg.guardian.id,
                    "relationship": sg.relationship,
                    "is_primary": sg.is_primary,
                })
            data["student_guardians"] = student_guardians_data
            
            # Add class_students as simple nested data (read response)
            class_students_data = []
            for cs in instance.class_students.select_related("class_obj").all():
                class_students_data.append({
                    "id": cs.id,
                    "class_id": cs.class_obj.id,
                    "is_current": cs.is_current,
                })
            data["class_students"] = class_students_data
        else:
            data["student_guardians"] = []
            data["class_students"] = []
        
        return data

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
        
        First class in class_students will be marked as is_current=true.
        """

        # Remove custom fields before Student.objects.create()
        student_guardians_data = validated_data.pop(
            "student_guardians",
            [],
        )

        class_students_data = validated_data.pop(
            "class_students",
            [],
        )

        # Create Student
        student = Student.objects.create(**validated_data)

        # Sync student guardians (create/update/delete)
        self._sync_student_guardians(
            student,
            student_guardians_data,
        )

        # Sync class assignments (create with is_current logic)
        self._sync_class_students(
            student,
            class_students_data,
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

        If class_students is provided: sync (create/update/delete with is_current).
        If class_students is omitted: keep existing.
        """

        # student_guardians:
        # If provided: process nested create/update/delete.
        # If not provided: keep existing guardians.
        student_guardians_data = validated_data.pop(
            "student_guardians",
            None,
        )

        # class_students:
        # If provided: replace/sync class assignments with is_current handling.
        # If not provided: keep existing classes.
        class_students_data = validated_data.pop(
            "class_students",
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

        if class_students_data is not None:
            self._sync_class_students(
                instance,
                class_students_data,
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
                        "password": "SecurePassword123!",
                        "first_name": "Jane",
                        "last_name": "Smith"
                    },
                    "relationship": "mother"
                }
            ]
        }

        Result:

        ID 10 -> UPDATE
        ID 11 -> DELETE
        guardian_id 5 -> CREATE (link student to existing guardian)
        "user" -> CREATE (new User, new Guardian, new StudentGuardian link)
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
                email = new_guardian_data.get("email")
                
                # Check if User with this email already exists
                existing_user = User.objects.filter(email=email).first()
                
                if existing_user:
                    # User exists, get or create Guardian for this User
                    guardian, _ = Guardian.objects.get_or_create(
                        user=existing_user,
                        defaults={
                            "name": f"{new_guardian_data.get('first_name', '')} {new_guardian_data.get('last_name', '')}".strip(),
                            "phone_number": new_guardian_data.get("phone_number"),
                            "image_data": new_guardian_data.get("image_data"),
                        }
                    )
                else:
                    # User doesn't exist, create User and Guardian
                    guardian = GuardianInlineSerializer().create(
                        new_guardian_data
                    )

            StudentGuardian.objects.create(
                student=student,
                guardian=guardian,
                **item,
            )

    # ========================================================
    # SYNC CLASS STUDENTS
    # ========================================================

    def _sync_class_students(self, student, class_students_data):
        """
        Rails-like nested class_students handling with is_current logic.

        When creating: first class is marked as is_current=true.
        When updating: handle create/update/delete with flexible is_current.

        Example:

        {
            "class_students": [
                {
                    "class_id": 1,
                    "is_current": true
                },
                {
                    "class_id": 2,
                    "is_current": false
                },
                {
                    "id": 5,
                    "is_current": true
                },
                {
                    "id": 6,
                    "_destroy": true
                }
            ]
        }

        Result:
        - Create new assignments for classes 1, 2
        - Update is_current for existing ID 5
        - Delete assignment ID 6
        """

        existing_assignments = {
            cs.id: cs
            for cs in student.class_students.all()
        }

        new_assignments = []
        is_current_count = 0

        for index, item in enumerate(class_students_data):

            # Get existing assignment ID.
            # None means this is a new assignment.
            assignment_id = item.pop("id", None)

            # Get destroy flag.
            destroy = item.pop("_destroy", False)

            # Get is_current value.
            is_current = item.pop("is_current", False)

            # Get class object.
            class_obj = item.pop("class_obj", None)

            # ------------------------------------------------
            # CREATE NEW ASSIGNMENT
            # ------------------------------------------------

            if assignment_id is None:

                if not class_obj:
                    raise serializers.ValidationError({
                        "class_students": (
                            f"'class_id' is required for new class assignment."
                        )
                    })

                # On creation, mark first class as is_current
                if index == 0 and not self.instance:
                    is_current = True

                new_assignments.append(
                    ClassStudent(
                        student=student,
                        class_obj=class_obj,
                        is_current=is_current,
                    )
                )

                if is_current:
                    is_current_count += 1

                continue

            # ------------------------------------------------
            # UPDATE OR DELETE EXISTING ASSIGNMENT
            # ------------------------------------------------

            assignment = existing_assignments.get(assignment_id)

            if not assignment:
                raise serializers.ValidationError({
                    "class_students": (
                        f"No existing assignment with "
                        f"id {assignment_id} "
                        f"for this student."
                    )
                })

            # DELETE existing assignment
            if destroy:
                assignment.delete()
                continue

            # UPDATE existing assignment
            assignment.is_current = is_current
            assignment.save()

            if is_current:
                is_current_count += 1

        # ------------------------------------------------
        # Create new assignments in bulk
        # ------------------------------------------------

        if new_assignments:
            ClassStudent.objects.bulk_create(new_assignments)

        # Optional: Validate only one is_current per student
        # Uncomment if strict validation is needed
        # if is_current_count > 1:
        #     raise serializers.ValidationError({
        #         "class_students": (
        #             "Only one class can be marked as current per student."
        #         )
        #     })


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
    """
    Detail response serializer for Student.
    Shows full nested data for guardians and classes.
    """
    student_guardians = StudentGuardianDetailSerializer(
        many=True,
        read_only=True,
    )

    class Meta(StudentSerializer.Meta):
        fields = StudentSerializer.Meta.fields
        read_only_fields = StudentSerializer.Meta.read_only_fields

    def to_representation(self, instance):
        """
        Detail response includes full class serializer data.
        """
        data = super().to_representation(instance)
        
        # Override class_students with full ClassSerializer data
        class_students_list = instance.class_students.select_related("class_obj").all()
        
        class_students_data = []
        for cs in class_students_list:
            class_students_data.append({
                "id": cs.id,
                "class_id": cs.class_obj.id,
                "is_current": cs.is_current,
                "class": ClassSerializer(cs.class_obj).data,
            })
        
        data["class_students"] = class_students_data
        return data


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