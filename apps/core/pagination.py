"""Shared pagination and ordering configuration for API list endpoints."""

from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsSetPagination(PageNumberPagination):
    """Expose pagination metadata in headers while preserving array response bodies."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    page_query_param = "page"

    def paginate_queryset(self, queryset, request, view=None):
        # Keep the existing API contract: list responses remain JSON arrays.
        self.request = request
        self.page = None
        self._count = queryset.count()
        return list(queryset)

    def get_paginated_response(self, data):
        count = self._count
        return Response(
            data,
            headers={
                "X-Total-Count": str(count),
                "X-Page": "1",
                "X-Page-Size": str(count),
                "X-Total-Pages": "1",
            },
        )


class SafeOrderingFilter(OrderingFilter):
    """Allow explicit ordering while keeping a stable primary-key tie-breaker."""

    ordering_param = "ordering"

    def get_ordering(self, request, queryset, view):
        ordering = super().get_ordering(request, queryset, view)
        if not ordering:
            return ordering

        if not any(field.lstrip("-") == "pk" for field in ordering):
            ordering = (*ordering, "pk")
        return ordering
