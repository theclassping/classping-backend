from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import viewsets

from apps.student_invoices.services import generate_manual_invoices

from .models import FeeType
from .serializers import FeeTypeSerializer, GenerateInvoicesSerializer


class FeeTypeViewSet(viewsets.ModelViewSet):

    queryset = FeeType.objects.select_related(
        "branch",
    ).all()

    serializer_class = FeeTypeSerializer

    permission_classes = [
        permissions.IsAuthenticated
    ]

    def get_queryset(self):
        queryset = super().get_queryset()

        branch_id = self.request.query_params.get("branch_id")
        is_active = self.request.query_params.get("is_active")

        if branch_id:
            queryset = queryset.filter(
                branch_id=branch_id
            )

        if is_active is not None:
            queryset = queryset.filter(
                is_active=is_active.lower() == "true"
            )

        return queryset

    @action(
        detail=True,
        methods=["post"],
        url_path="generate-invoices",
    )
    def generate_invoices(self, request, pk=None):
        fee_type = self.get_object()
        serializer = GenerateInvoicesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if fee_type.is_recurring:
            return Response(
                {
                    "detail": (
                        "Manual invoices can only be generated for "
                        "non-recurring fee types."
                    )
                },
                status=400,
            )

        data = serializer.validated_data
        created_count = generate_manual_invoices(
            fee_type=fee_type,
            invoice_date=data["invoice_date"],
            due_date=data.get("due_date"),
            remark=data.get("remark"),
        )

        return Response(
            {
                "detail": "Student invoices generated successfully.",
                "created_count": created_count,
            }
        )