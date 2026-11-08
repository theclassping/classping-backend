"""Shared pagination, filtering and ordering for API list endpoints.

A list view opts in with ``filter_backends = LIST_FILTER_BACKENDS`` and
declares what may be filtered, searched and sorted:

    filter_fields = {"status": "status", "student_id": "student_id"}  # ?status=a,b
    date_filter_field = "created_at"        # ?date_from=2026-11-01&date_to=2026-11-30
    search_fields = ["payment_no", "student__first_name"]             # ?search=
    ordering_fields = ["created_at", "amount"]                        # ?ordering=-amount
    ordering = ["-created_at"]
"""

import datetime

from django.core.exceptions import FieldDoesNotExist, ValidationError
from rest_framework.filters import BaseFilterBackend, OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.core.exceptions import InvalidFilter


class StandardResultsSetPagination(PageNumberPagination):
    """Array response bodies with pagination metadata in headers.

    Without ``?page`` every row is returned (the existing API contract); with
    ``?page`` (and optional ``?page_size``) one page is returned.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    page_query_param = "page"

    def paginate_queryset(self, queryset, request, view=None):
        if self.page_query_param in request.query_params:
            return super().paginate_queryset(queryset, request, view)
        # Keep the existing API contract: list responses remain JSON arrays.
        self.request = request
        self.page = None
        self._count = queryset.count()
        return list(queryset)

    def get_paginated_response(self, data):
        if self.page is None:
            count = self._count
            page_number, page_size, total_pages = 1, count, 1
        else:
            paginator = self.page.paginator
            count = paginator.count
            page_number, page_size, total_pages = self.page.number, paginator.per_page, paginator.num_pages
        return Response(
            data,
            headers={
                "X-Total-Count": str(count),
                "X-Page": str(page_number),
                "X-Page-Size": str(page_size),
                "X-Total-Pages": str(total_pages),
            },
        )

    def get_paginated_response_schema(self, schema):
        # The body stays a plain array; metadata is in the headers.
        return schema


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


class QueryParamFilter(BaseFilterBackend):
    """Exact-match and date-range filters declared on the view.

    - ``filter_fields`` {param: lookup}: ``?param=a`` or ``?param=a,b`` (any of);
      values are converted and validated by the model field (booleans accept
      true/false, choices must be valid).
    - ``date_filter_field``: ``?date_from=`` / ``?date_to=`` (YYYY-MM-DD,
      inclusive, local time).
    Invalid values -> 400 INVALID_FILTER. Undeclared params are ignored.
    Runs after get_queryset(), so it only narrows already-scoped rows.
    """

    date_from_param = "date_from"
    date_to_param = "date_to"

    def filter_queryset(self, request, queryset, view):
        params = request.query_params
        to_many = False
        for param, lookup in getattr(view, "filter_fields", {}).items():
            raw = params.get(param, "").strip()
            if not raw:
                continue
            field, spans_many = self._resolve(queryset.model, lookup)
            to_many = to_many or spans_many
            values = [self._to_python(field, param, value.strip()) for value in raw.split(",") if value.strip()]
            if len(values) == 1:
                queryset = queryset.filter(**{lookup: values[0]})
            else:
                queryset = queryset.filter(**{lookup + "__in": values})

        date_field = getattr(view, "date_filter_field", None)
        if date_field:
            for param, operator in ((self.date_from_param, "gte"), (self.date_to_param, "lte")):
                raw = params.get(param, "").strip()
                if not raw:
                    continue
                try:
                    value = datetime.date.fromisoformat(raw)
                except ValueError:
                    raise InvalidFilter("{} must be a date (YYYY-MM-DD).".format(param), param=param)
                queryset = queryset.filter(**{"{}__date__{}".format(date_field, operator): value})
        return queryset.distinct() if to_many else queryset

    @staticmethod
    def _resolve(model, lookup):
        """The model field a lookup ends at, and whether it crosses a to-many relation."""
        field, spans_many = None, False
        for name in lookup.split("__"):
            try:
                field = model._meta.get_field(name)
            except FieldDoesNotExist:
                raise ValueError("Unknown filter lookup {} on {}".format(lookup, model.__name__))
            spans_many = spans_many or field.one_to_many or field.many_to_many
            if field.is_relation and field.related_model is not None:
                model = field.related_model
        if field.is_relation and not field.concrete:
            field = model._meta.pk
        elif field.is_relation:
            field = field.target_field
        return field, spans_many

    @staticmethod
    def _to_python(field, param, value):
        if field.get_internal_type() == "BooleanField":
            value = {"true": True, "1": True, "false": False, "0": False}.get(value.lower(), value)
        try:
            value = field.to_python(value)
        except ValidationError:
            raise InvalidFilter("Invalid value for {}.".format(param), param=param)
        if field.choices and value not in {choice for choice, _ in field.flatchoices}:
            raise InvalidFilter("Invalid value for {}.".format(param), param=param)
        return value

    def get_schema_operation_parameters(self, view):
        parameters = [
            {
                "name": param,
                "required": False,
                "in": "query",
                "description": "Filter by {} (comma-separated for any of).".format(lookup),
                "schema": {"type": "string"},
            }
            for param, lookup in getattr(view, "filter_fields", {}).items()
        ]
        if getattr(view, "date_filter_field", None):
            for param, label in ((self.date_from_param, "From"), (self.date_to_param, "To")):
                parameters.append(
                    {
                        "name": param,
                        "required": False,
                        "in": "query",
                        "description": "{} date, inclusive (YYYY-MM-DD).".format(label),
                        "schema": {"type": "string", "format": "date"},
                    }
                )
        return parameters


# For list views: filters, ?search= (DRF SearchFilter) and ?ordering=.
LIST_FILTER_BACKENDS = [QueryParamFilter, SearchFilter, SafeOrderingFilter]
