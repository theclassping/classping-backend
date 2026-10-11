"""Shared pagination and ordering configuration for API list endpoints."""

from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Consistent, bounded page-number pagination for every API list view."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    page_query_param = "page"


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
