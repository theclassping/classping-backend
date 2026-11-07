from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .selectors import get_parent_context
from .serializers import ParentContextQuerySerializer, ParentContextSerializer


class ParentContextView(APIView):
    """Everything the parent dashboard layout needs, in one call.

    Replaces the layout's separate student, class, branch and school calls;
    each part keeps the shape of the endpoint it replaces.
    """

    serializer_class = ParentContextSerializer

    @extend_schema(
        parameters=[OpenApiParameter("student_id", int, required=False)],
        responses=ParentContextSerializer,
    )
    def get(self, request):
        if str(request.user.role).upper() != "PARENT":
            raise PermissionDenied("Only parent accounts have a parent context.")

        query = ParentContextQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        context = get_parent_context(request.user, query.validated_data.get("student_id"))
        return Response(ParentContextSerializer(context, context={"request": request}).data)
