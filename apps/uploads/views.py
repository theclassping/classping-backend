"""
API views for media upload operations.
"""
import os
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.conf import settings

from apps.uploads.services.media import MediaService
from apps.uploads.serializers import (
    PresignUrlSerializer,
    PresignUrlResponseSerializer,
)


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
    permission_classes = [IsAuthenticated]
    
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
    permission_classes = [IsAuthenticated]
    
    def put(self, request, file_key):
        """Handle file upload via PUT request."""
        try:
            # Ensure media directory exists
            media_root = settings.MEDIA_ROOT
            os.makedirs(media_root, exist_ok=True)
            
            # Create subdirectories for file_key path
            file_path = os.path.join(media_root, file_key)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Save the binary file
            with open(file_path, 'wb') as f:
                f.write(request.body)
            
            return Response(status=status.HTTP_204_NO_CONTENT)
        
        except Exception as e:
            return Response(
                {'error': f'File upload failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
