"""
Thin views: access check -> service call -> render. No business rules here.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.core.access import ScopedQuerysetMixin
from apps.core.pagination import LIST_FILTER_BACKENDS
from apps.users.permissions import RoleBasedAccessPermission

from . import services
from .exceptions import IdempotencyKeyRequired, StudentRequired
from .selectors import gateway_payment_queryset
from .serializers import (
    CancelRequestSerializer,
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

    @extend_schema(
        parameters=[OpenApiParameter("student_id", OpenApiTypes.INT, required=True)],
        responses=StudentPayabilitySerializer,
    )
    def get(self, request):
        student_id = request.query_params.get("student_id")
        if not student_id or not student_id.isdigit():
            raise StudentRequired()
        result = services.get_student_payability(request.user, int(student_id))
        return Response(StudentPayabilitySerializer(result).data)


class GatewayChannelView(APIView):
    """B1 GET gateway/channels?invoice_ids=1,2"""

    permission_classes = [RoleBasedAccessPermission]

    @extend_schema(
        parameters=[OpenApiParameter("invoice_ids", OpenApiTypes.STR, required=True, description="1-5 invoice ids, e.g. 11,12")],
        responses=CheckoutQuoteSerializer,
    )
    def get(self, request):
        invoice_ids = parse_invoice_ids(request.query_params.get("invoice_ids", ""))
        quote = services.get_checkout_quote(request.user, invoice_ids)
        return Response(CheckoutQuoteSerializer(quote).data)


class GatewayCheckoutView(APIView):
    """B2 POST gateway/checkout (header Idempotency-Key)"""

    permission_classes = [RoleBasedAccessPermission]
    throttle_classes = [GatewayCheckoutThrottle]

    @extend_schema(
        parameters=[OpenApiParameter("Idempotency-Key", OpenApiTypes.STR, OpenApiParameter.HEADER, required=True)],
        request=CheckoutRequestSerializer,
        responses={201: GatewayPaymentDetailSerializer, 200: GatewayPaymentDetailSerializer},
    )
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
    filter_backends = LIST_FILTER_BACKENDS
    filter_fields = {"status": "status", "student_id": "student_id", "needs_refund": "needs_refund"}
    date_filter_field = "created_at"
    search_fields = ["payment_no", "student__first_name", "student__last_name"]
    ordering_fields = ["created_at", "amount", "status", "paid_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return GatewayPaymentSummarySerializer
        return GatewayPaymentDetailSerializer

    @extend_schema(request=CancelRequestSerializer, responses=GatewayPaymentDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """B5 / C1b POST gateway/payments/{id}/cancel/ {"reason": "..."}"""
        payload = CancelRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.cancel_gateway_payment(request.user, pk, payload.validated_data["reason"])
        gateway_payment = self.get_queryset().get(pk=pk)
        return Response(GatewayPaymentDetailSerializer(gateway_payment).data)
