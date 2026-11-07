"""
Thin views: access check -> service call -> render. No business rules here.
"""

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.core.access import ScopedQuerysetMixin
from apps.users.permissions import RoleBasedAccessPermission

from . import services
from .exceptions import IdempotencyKeyRequired, StudentRequired
from .selectors import gateway_payment_queryset
from .serializers import (
    CheckoutQuoteSerializer,
    CheckoutRequestSerializer,
    GatewayPaymentDetailSerializer,
    GatewayPaymentSummarySerializer,
    StudentPayabilitySerializer,
    parse_invoice_ids,
)


class GatewayCheckoutThrottle(UserRateThrottle):
    scope = "gateway_checkout"


class GatewayInvoiceView(APIView):
    """B0 GET gateway/invoices?student_id="""

    permission_classes = [RoleBasedAccessPermission]

    def get(self, request):
        student_id = request.query_params.get("student_id")
        if not student_id or not student_id.isdigit():
            raise StudentRequired()
        result = services.get_student_payability(request.user, int(student_id))
        return Response(StudentPayabilitySerializer(result).data)


class GatewayChannelView(APIView):
    """B1 GET gateway/channels?invoice_ids=1,2"""

    permission_classes = [RoleBasedAccessPermission]

    def get(self, request):
        invoice_ids = parse_invoice_ids(request.query_params.get("invoice_ids", ""))
        quote = services.get_checkout_quote(request.user, invoice_ids)
        return Response(CheckoutQuoteSerializer(quote).data)


class GatewayCheckoutView(APIView):
    """B2 POST gateway/checkout (header Idempotency-Key)"""

    permission_classes = [RoleBasedAccessPermission]
    throttle_classes = [GatewayCheckoutThrottle]

    def post(self, request):
        idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
        if not idempotency_key or len(idempotency_key) > 100:
            raise IdempotencyKeyRequired()
        payload = CheckoutRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        gateway_payment, created = services.create_gateway_checkout(
            request.user,
            payload.validated_data["invoice_ids"],
            payload.validated_data["channel"],
            idempotency_key,
        )
        return Response(
            GatewayPaymentDetailSerializer(gateway_payment).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class GatewayPaymentViewSet(ScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """B3 / B4 GET gateway/payments[/{id}] (parents: their students; staff: their branch)."""

    permission_classes = [RoleBasedAccessPermission]
    queryset = gateway_payment_queryset()

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        if params.get("student_id", "").isdigit():
            queryset = queryset.filter(student_id=params["student_id"])
        search = params.get("search")
        if search:
            queryset = queryset.filter(
                Q(payment_no__icontains=search)
                | Q(student__first_name__icontains=search)
                | Q(student__last_name__icontains=search)
            )
        return queryset

    def get_serializer_class(self):
        if self.action == "retrieve":
            return GatewayPaymentDetailSerializer
        return GatewayPaymentSummarySerializer
