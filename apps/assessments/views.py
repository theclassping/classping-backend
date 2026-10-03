from rest_framework import viewsets
from apps.users.permissions import RoleBasedAccessPermission

from .models import AssessmentImage
from .serializers import AssessmentImageSerializer


class AssessmentImageViewSet(viewsets.ModelViewSet):
    """API endpoint for assessment images."""
    queryset = AssessmentImage.objects.all()
    serializer_class = AssessmentImageSerializer
    permission_classes = [RoleBasedAccessPermission]
