from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.uploads.services.media import MediaService
from .models import Guardian

User = get_user_model()


class GuardianSerializer(serializers.ModelSerializer):
    user_id = serializers.PrimaryKeyRelatedField(
        source="user",
        queryset=User.objects.all(),
    )
    
    image_url = serializers.SerializerMethodField()

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

        # Create User first (with temp password if not provided)
        temp_password = password or "temp_password_123"
        
        user = User.objects.create_user(
            email=validated_data["email"],
            password=temp_password,
            first_name=first_name,
            last_name=last_name,
            role=User.Role.PARENT,
        )

        # If no password provided, generate default password: cp{first_name}{last_name}{user_id}
        if not password:
            default_password = f"cp{first_name}{last_name}{user.id}"
            user.set_password(default_password)
            user.save()

        # Combine first_name and last_name for Guardian.name field
        name = f"{first_name} {last_name}"

        return Guardian.objects.create(user=user, name=name, **validated_data)