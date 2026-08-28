from rest_framework import viewsets

from .models import Guardian
from .serializers import GuardianSerializer


class GuardianViewSet(viewsets.ModelViewSet):
    queryset = Guardian.objects.all().order_by("-id")
    serializer_class = GuardianSerializer