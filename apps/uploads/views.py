"""
API views for media upload operations.
"""
import os
from rest_framework import status
from rest_framework.response import Response
from apps.users.permissions import RoleBasedAccessPermission
from rest_framework.views import APIView
from django.conf import settings

from apps.uploads.services.media import MediaService
from apps.uploads.serializers import (
    PresignUrlSerializer,
    PresignUrlResponseSerializer,
)
from apps.uploads.storage import get_storage, validate_file_key


class PresignUrlView(APIView):
    """
    POST /api/media/presign
    
    Request body:
    {
        "filename": "logo-1.png",
        "content_type": "image/png",
        "expires_in": 3600
    }
    
    Response:
    {
        "file_key": "2025/01/15/abc123def456.png",
        "presigned_url": "https://...",
        "expires_in": 3600,
        "content_type": "image/png"
    }
    """
    permission_classes = [RoleBasedAccessPermission]
    
    def post(self, request):
        serializer = PresignUrlSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            result = MediaService.generate_presign_url(
                filename=serializer.validated_data['filename'],
                content_type=serializer.validated_data['content_type'],
                expires_in=serializer.validated_data.get('expires_in', 3600),
            )
            
            response_serializer = PresignUrlResponseSerializer(result)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UploadView(APIView):
    """
    PUT /api/media/upload/{file_key}
    
    Upload binary file data to local storage.
    
    Request:
    - Method: PUT
    - Content-Type: image/jpeg (or appropriate MIME type)
    - Body: Binary file data
    
    Response:
    - 204 No Content (file saved successfully)
    """
    permission_classes = [RoleBasedAccessPermission]
    
    def put(self, request, file_key):
        """Handle file upload via PUT request."""
        try:
            safe_file_key = validate_file_key(file_key)
            media_root = os.path.abspath(settings.MEDIA_ROOT)
            os.makedirs(media_root, exist_ok=True)

            file_path = os.path.abspath(os.path.join(media_root, safe_file_key))
            if os.path.commonpath([media_root, file_path]) != media_root:
                return Response(
                    {'error': 'Invalid file path.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, 'wb') as f:
                f.write(request.body)

            return Response(status=status.HTTP_204_NO_CONTENT)

        except ValueError as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {'error': f'File upload failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class MediaDownloadUrlView(APIView):
    permission_classes = [RoleBasedAccessPermission]

    def get(self, request):
        file_key = request.query_params.get("file_key")

        if not file_key:
            return Response(
                {"error": "file_key is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            safe_file_key = validate_file_key(file_key)
            storage = get_storage()

            if not storage.verify_object_exists(safe_file_key):
                return Response(
                    {"error": "File not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            url = storage.generate_presigned_download_url(
                file_key=safe_file_key,
                expires_in=3600,
            )

            return Response(
                {
                    "url": url,
                    "expires_in": 3600,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )