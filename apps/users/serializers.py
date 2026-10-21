from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.utils import get_md5_hash_password
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from apps.guardians.models import Guardian
from apps.students.models import Student
from .role_policy import check_account_management
from .models import RevokedTokenSession

User = get_user_model()


class PasswordAwareTokenRefreshSerializer(TokenRefreshSerializer):
    """Reject stale password claims even if a refresh escaped the blacklist."""

    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        sid = refresh.get("sid")
        if not sid or RevokedTokenSession.objects.filter(sid=sid).exists():
            raise AuthenticationFailed("Session has been revoked. Please log in again.")
        user = User.objects.filter(
            **{api_settings.USER_ID_FIELD: refresh.get(api_settings.USER_ID_CLAIM)}
        ).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed("No active account found for the given token.")
        if refresh.get(api_settings.REVOKE_TOKEN_CLAIM) != get_md5_hash_password(user.password):
            raise AuthenticationFailed("Password has changed. Please log in again.")
        return super().validate(attrs)


class LoginTokenSerializer(TokenObtainPairSerializer):
    """JWT response serializer with the authenticated user's details."""

    user = serializers.SerializerMethodField()

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Simple JWT copies this claim to every derived access/rotated refresh.
        token["sid"] = token["jti"]
        return token
    
    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = self.get_user(self.user)
        return data

    def get_user(self, obj):
        user = self.user
        data = UserSerializer(user).data
        if str(user.role).lower() == User.Role.PARENT.lower():
            guardian_students = []
            guardian = Guardian.objects.filter(user_id=user.id).first()
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
    student_id = serializers.PrimaryKeyRelatedField(
        queryset=Student.objects.all(),
        required=False, write_only=True,
    )
    staff_profile = serializers.DictField(required=False, write_only=True)
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
            "student_id",
            "staff_profile",
        ]

    def validate(self, attrs):
        check_account_management(
            self.context["request"].user,
            new_role=attrs.get("role", User.Role.STAFF),
        )
        role = attrs.get("role", User.Role.STAFF)
        actor = self.context["request"].user
        if "student_id" in attrs:
            from apps.core.access import scope_queryset
            if not scope_queryset(Student.objects.all(), actor).filter(pk=attrs["student_id"].pk).exists():
                raise serializers.ValidationError({"student_id": "Student is outside your scope."})
        if actor.role != User.Role.ADMIN:
            if role == User.Role.PARENT and "student_id" not in attrs:
                raise serializers.ValidationError({"student_id": "A student in your scope is required."})
            if role in (User.Role.STAFF, User.Role.TEACHER) and "staff_profile" not in attrs:
                raise serializers.ValidationError({"staff_profile": "A staff profile in your branch is required."})
        if "student_id" in attrs and role != User.Role.PARENT:
            raise serializers.ValidationError({"student_id": "Only PARENT accounts can be linked to a student."})
        if "staff_profile" in attrs:
            from apps.core.access import scope_queryset
            from apps.staffs.serializers import StaffSerializer
            if role not in (User.Role.STAFF, User.Role.TEACHER):
                raise serializers.ValidationError({"staff_profile": "Only STAFF and TEACHER accounts can have a staff profile."})
            profile = dict(attrs["staff_profile"])
            if "user" in profile:
                raise serializers.ValidationError({"staff_profile": "The new account is linked automatically."})
            profile.update(email=attrs["email"], first_name=attrs.get("first_name", ""), last_name=attrs.get("last_name", ""))
            self.staff_serializer = StaffSerializer(data=profile, context=self.context)
            branch_field = self.staff_serializer.fields["branch"]
            branch_field.queryset = scope_queryset(branch_field.queryset, actor)
            self.staff_serializer.is_valid(raise_exception=True)
            expected = User.Role.TEACHER if self.staff_serializer.validated_data["staff_type"] == "teacher" else User.Role.STAFF
            if role != expected:
                raise serializers.ValidationError({"staff_profile": "Staff type must match the account role."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        student = validated_data.pop("student_id", None)
        profile = validated_data.pop("staff_profile", None)

        user = User.objects.create_user(
            password=password,
            **validated_data,
        )

        if profile is not None:
            self.staff_serializer.save(user=user)
        if student is not None:
            from apps.students.models import StudentGuardian
            guardian = Guardian.objects.create(user=user, name=user.full_name, email=user.email)
            StudentGuardian.objects.create(student=student, guardian=guardian, relationship="other")

        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
        ]

    def validate(self, attrs):
        actor = self.context["request"].user
        if actor.role == User.Role.PARENT and actor.pk == self.instance.pk:
            if "role" in attrs or "is_active" in attrs:
                raise serializers.ValidationError(
                    "Parents can edit their profile, but cannot change role or account status."
                )
        else:
            check_account_management(actor, self.instance, attrs.get("role"))
        return attrs

    def update(self, instance, validated_data):
        user = super().update(instance, validated_data)
        if "email" in validated_data:
            guardian = getattr(user, "guardian", None)
            if guardian:
                guardian.email = user.email
                guardian.save(update_fields=["email", "updated_at"])
        return user

class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, attrs):
        try:
            self.token = RefreshToken(attrs["refresh"])
        except TokenError as exc:
            raise serializers.ValidationError({"refresh": "Invalid refresh token."}) from exc
        request = self.context["request"]
        if (
            str(self.token.get(api_settings.USER_ID_CLAIM)) != str(getattr(request.user, api_settings.USER_ID_FIELD))
            or not self.token.get("sid")
            or self.token.get("sid") != request.auth.get("sid")
        ):
            raise serializers.ValidationError({"refresh": "Refresh token must belong to the current login session."})
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
