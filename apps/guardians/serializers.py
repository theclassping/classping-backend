from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.uploads.services.media import MediaService
from apps.students.models import Student, StudentGuardian
from apps.users.managers import generate_temporary_password
from .models import Guardian

User = get_user_model()


class GuardianStudentRelationSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    student_id = serializers.PrimaryKeyRelatedField(
        source="student",
        queryset=Student.objects.all(),
    )

    class Meta:
        model = StudentGuardian
        fields = ["id", "student_id", "relationship", "is_primary"]


class GuardianSerializer(serializers.ModelSerializer):
    user_id = serializers.PrimaryKeyRelatedField(
        source="user",
        queryset=User.objects.all(),
    )
    
    image_url = serializers.SerializerMethodField()
    student_guardians = GuardianStudentRelationSerializer(many=True, required=False)

    class Meta:
        model = Guardian

        fields = [
            "id",
            "user_id",
            "name",
            "phone_number",
            "email",
            "image_data",
            "image_url",
            "student_guardians",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "image_url",
            "created_at",
            "updated_at",
        ]
    
    def get_image_url(self, obj):
        """Get the full URL for the guardian's image if metadata exists."""
        return obj.image_url
    
    def validate(self, attrs):
        """Process image_data if provided."""
        user = attrs.get("user", getattr(self.instance, "user", None))
        if user and user.role != User.Role.PARENT:
            raise serializers.ValidationError({
                "user_id": "A guardian must be linked to a user with the PARENT role."
            })

        if 'image_data' in attrs and attrs['image_data']:
            image_data_input = attrs['image_data']
            if isinstance(image_data_input, str):
                try:
                    processed_metadata = MediaService.process_image_data(image_data_input)
                    attrs['image_data'] = processed_metadata
                except FileNotFoundError:
                    raise serializers.ValidationError({
                        "image_data": "File not found. Please provide the full file path, e.g. 'C:/Users/audia/Downloads/brownies.jpg'"
                    })
                except Exception as e:
                    raise serializers.ValidationError({
                        "image_data": f"Error processing image: {str(e)}"
                    })
        
        return attrs

    def create(self, validated_data):
        relations = validated_data.pop("student_guardians", [])
        guardian = super().create(validated_data)
        self._sync_student_guardians(guardian, relations)
        return guardian

    def update(self, instance, validated_data):
        relations = validated_data.pop("student_guardians", None)
        guardian = super().update(instance, validated_data)
        if relations is not None:
            self._sync_student_guardians(guardian, relations)
        return guardian

    def _sync_student_guardians(self, guardian, relations):
        for relation_data in relations:
            relation_id = relation_data.pop("id", None)
            student = relation_data.pop("student")
            relation = guardian.student_guardians.filter(
                pk=relation_id
            ).first() if relation_id else guardian.student_guardians.filter(
                student=student
            ).first()

            if relation:
                relation.student = student
                for field, value in relation_data.items():
                    setattr(relation, field, value)
                relation.save()
            else:
                StudentGuardian.objects.create(
                    guardian=guardian,
                    student=student,
                    **relation_data,
                )


class GuardianInlineSerializer(serializers.ModelSerializer):
    # Creates the login User account together with the Guardian record.
    # If user with email already exists, it's handled in StudentSerializer._sync_student_guardians()
    password = serializers.CharField(write_only=True, min_length=8, required=False, allow_blank=True)
    first_name = serializers.CharField(write_only=True, required=True)
    last_name = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = Guardian
        fields = [
            "email",
            "password",
            "first_name",
            "last_name",
            "phone_number",
            "image_data",
        ]

    def validate(self, attrs):
        """Process image_data if provided."""
        if 'image_data' in attrs and attrs['image_data']:
            image_data_input = attrs['image_data']
            if isinstance(image_data_input, str):
                try:
                    processed_metadata = MediaService.process_image_data(image_data_input)
                    attrs['image_data'] = processed_metadata
                except FileNotFoundError:
                    raise serializers.ValidationError({
                        "image_data": "File not found. Please provide the full file path, e.g. 'C:/Users/audia/Downloads/brownies.jpg'"
                    })
                except Exception as e:
                    raise serializers.ValidationError({
                        "image_data": f"Error processing image: {str(e)}"
                    })
        
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        first_name = validated_data.pop("first_name")
        last_name = validated_data.pop("last_name")

        temporary_password = (
            generate_temporary_password() if not password else None
        )
        
        user = User.objects.create_user(
            email=validated_data["email"],
            password=password,
            temporary_password=temporary_password,
            first_name=first_name,
            last_name=last_name,
            role=User.Role.PARENT,
        )

        # Combine first_name and last_name for Guardian.name field
        name = f"{first_name} {last_name}"

        return Guardian.objects.create(user=user, name=name, **validated_data)
