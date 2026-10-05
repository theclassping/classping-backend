from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class LoginTokenSerializer(TokenObtainPairSerializer):
    """JWT response serializer with the authenticated user's details."""

    user = serializers.SerializerMethodField()

    def get_user(self, obj):
        user = self.user
        data = UserSerializer(user).data

        if str(user.role).lower() == User.Role.PARENT.lower():
            guardian_students = []
            guardian = getattr(user, "guardian", None)
            if guardian:
                relations = guardian.student_guardians.select_related("student").all()
                for relation in relations:
                    student = relation.student
                    guardian_students.append({
                        "id": relation.id,
                        "student_id": student.id,
                        "first_name": student.first_name,
                        "middle_name": student.middle_name,
                        "last_name": student.last_name,
                        "nickname": student.nickname,
                        "date_of_birth": student.date_of_birth,
                        "image_data": student.image_data,
                        "image_url": student.image_url,
                        "gender": student.gender,
                        "address": student.address,
                        "location_id": student.location_id,
                        "enroll_date": student.enroll_date,
                        "status": student.status,
                        "relationship": relation.relationship,
                        "is_primary": relation.is_primary,
                    })

            data["guardian_students"] = guardian_students

        return data


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "full_name",
            "created_at",
            "updated_at",
        ]


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
    )

    class Meta:
        model = User
        fields = [
            "email",
            "password",
            "first_name",
            "last_name",
            "role",
        ]

    def create(self, validated_data):
        password = validated_data.pop("password")

        user = User.objects.create_user(
            password=password,
            **validated_data,
        )

        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "role",
            "is_active",
        ]

class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, attrs):
        try:
            self.token = RefreshToken(attrs["refresh"])
        except TokenError as exc:
            raise serializers.ValidationError({"refresh": "Invalid refresh token."}) from exc
        return attrs

    def save(self, **kwargs):
        self.token.blacklist()

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
    )

    def __init__(self, *args, **kwargs):
        self.user = None
        super().__init__(*args, **kwargs)

    def validate_new_password(self, value):
        validate_password(value, user=self.user)
        return value

    def validate(self, attrs):
        attrs["new_password"] = self.validate_new_password(attrs["new_password"])
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(
        write_only=True,
        min_length=8,
    )
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
    )

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        user = self.context["request"].user
        validate_password(value, user=user)
        return value
