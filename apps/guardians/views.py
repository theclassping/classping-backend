from rest_framework import viewsets
from django.db.models import Q

from .models import Guardian
from .serializers import GuardianSerializer


class GuardianViewSet(viewsets.ModelViewSet):
    queryset = Guardian.objects.all().order_by("-id")
    serializer_class = GuardianSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search") or self.request.query_params.get("q")
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(email__icontains=search) | Q(phone_number__icontains=search))
        return queryset
