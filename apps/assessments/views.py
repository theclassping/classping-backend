from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import AssessmentImage
from .serializers import AssessmentImageSerializer


class AssessmentImageViewSet(viewsets.ModelViewSet):
    """API endpoint for assessment images."""
    queryset = AssessmentImage.objects.all()
    serializer_class = AssessmentImageSerializer
    permission_classes = [IsAuthenticated]
