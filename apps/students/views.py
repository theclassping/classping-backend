from apps.core.access import ScopedQuerysetMixin, scope_queryset
from rest_framework import viewsets
from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Student, StudentGuardian
from .serializers import (
    StudentSerializer,
    StudentDetailSerializer,
    StudentGuardianSerializer,
)
from apps.student_invoices.models import StudentInvoice
from apps.student_invoices.serializers import StudentInvoiceSerializer


class StudentViewSet(ScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = StudentSerializer

    def get_queryset(self):
        if self.action == "retrieve":
            queryset = Student.objects.prefetch_related(
                "student_guardians__guardian",
                "class_students__class_obj",
            ).order_by("-id")
        else:
            queryset = Student.objects.order_by("-id")
        search = self.request.query_params.get("search") or self.request.query_params.get("q")
        status = self.request.query_params.get("status")
        guardian_id = self.request.query_params.get("guardian_id")
        class_id = self.request.query_params.get("class_id")
        branch_id = self.request.query_params.get("branch_id")
        if search:
            queryset = queryset.filter(Q(first_name__icontains=search) | Q(middle_name__icontains=search) | Q(last_name__icontains=search) | Q(nickname__icontains=search))
        if status:
            queryset = queryset.filter(status=status)
        if branch_id:
            queryset = queryset.filter(class_students__class_obj__branch_id=branch_id)
        if guardian_id:
            queryset = queryset.filter(
                student_guardians__guardian_id=guardian_id
            )
        if class_id:
            queryset = queryset.filter(
                class_students__class_obj_id=class_id
            )

        return scope_queryset(queryset.distinct(), self.request.user)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return StudentDetailSerializer

        return StudentSerializer

    @action(
        detail=True,
        methods=["get"],
        url_path="invoices",
    )
    def invoices(self, request, pk=None):
        # This action builds its own invoice queryset, so enforce the same
        # student visibility check used by retrieve/update actions.
        self.get_object()

        invoices = (
            StudentInvoice.objects
            .filter(
                class_student__student_id=pk
            )
            .select_related(
                "class_student__student",
                "class_student__class_obj",
            )
        )

        # Filter by status
        status = request.query_params.get("status")

        if status:
            invoices = invoices.filter(
                status=status
            )

        invoices = self.filter_queryset(invoices)
        page = self.paginate_queryset(invoices)
        serializer = StudentInvoiceSerializer(page if page is not None else invoices, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

class StudentGuardianViewSet(ScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = StudentGuardian.objects.select_related(
        "student",
        "guardian",
    ).all()

    serializer_class = StudentGuardianSerializer 
