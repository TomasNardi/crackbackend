"""
Customers Views
================
Endpoints de la cuenta del comprador (`/api/v1/customers/...`).
"""

from django.db import transaction
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import generics, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Order

from .authentication import CustomerAuthentication, IsCustomer
from .models import CustomerAddress
from .serializers import CustomerAddressSerializer, CustomerOrderSerializer, CustomerSerializer
from .services import sync_session, token_from_request
from .supabase_auth import AuthNotConfigured, InvalidToken, get_verifier


class CustomerView:
    """Base de los endpoints que necesitan sesión de comprador."""

    authentication_classes = [CustomerAuthentication]
    permission_classes = [IsCustomer]


class SessionView(APIView):
    """POST al entrar (y en cada carga con sesión): crea la cuenta si es nueva
    y le trae las compras que haya hecho como invitado con ese email."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @method_decorator(ratelimit(key="ip", rate="30/m", method="POST", block=True))
    def post(self, request):
        try:
            identity = get_verifier().verify(token_from_request(request))
        except AuthNotConfigured as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except InvalidToken as exc:
            raise AuthenticationFailed(str(exc)) from exc

        customer, linked = sync_session(
            identity, marketing_opt_in=request.data.get("marketing_opt_in") is True
        )
        return Response({"profile": CustomerSerializer(customer).data, "linked_orders": linked})


class ProfileView(CustomerView, generics.RetrieveUpdateAPIView):
    serializer_class = CustomerSerializer
    http_method_names = ["get", "patch"]

    def get_object(self):
        return self.request.user.customer


class AddressListView(CustomerView, generics.ListCreateAPIView):
    serializer_class = CustomerAddressSerializer
    pagination_class = None

    def get_queryset(self):
        return CustomerAddress.objects.filter(customer=self.request.user.customer)

    @transaction.atomic
    def perform_create(self, serializer):
        customer = self.request.user.customer
        kind = serializer.validated_data.get("kind", CustomerAddress.KIND_HOME)
        same_kind = customer.addresses.filter(kind=kind)
        # La primera de cada tipo es la predeterminada; si llega otra marcada
        # como predeterminada, deja de serlo la anterior del mismo tipo.
        is_default = serializer.validated_data.get("is_default") or not same_kind.exists()
        if is_default:
            same_kind.update(is_default=False)
        serializer.save(customer=customer, is_default=is_default)


class AddressDetailView(CustomerView, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CustomerAddressSerializer
    http_method_names = ["get", "patch", "delete"]

    def get_queryset(self):
        return CustomerAddress.objects.filter(customer=self.request.user.customer)

    @transaction.atomic
    def perform_update(self, serializer):
        previous_kind = serializer.instance.kind
        address = serializer.save()
        others = address.customer.addresses.filter(kind=address.kind).exclude(pk=address.pk)
        if address.is_default:
            others.update(is_default=False)
        elif not others.filter(is_default=True).exists():
            # Un tipo con direcciones no puede quedar sin predeterminada.
            CustomerAddress.objects.filter(pk=address.pk).update(is_default=True)
            address.is_default = True
        if previous_kind != address.kind:
            _ensure_default(address.customer, previous_kind)

    @transaction.atomic
    def perform_destroy(self, instance):
        customer, kind = instance.customer, instance.kind
        instance.delete()
        _ensure_default(customer, kind)


def _ensure_default(customer, kind):
    """Si quedan direcciones de ese tipo y ninguna es predeterminada, pasa a serlo la más nueva."""
    same_kind = customer.addresses.filter(kind=kind)
    if not same_kind.filter(is_default=True).exists():
        newest = same_kind.order_by("-created_at").first()
        if newest:
            CustomerAddress.objects.filter(pk=newest.pk).update(is_default=True)


class OrderListView(CustomerView, generics.ListAPIView):
    serializer_class = CustomerOrderSerializer
    pagination_class = None

    def get_queryset(self):
        return (
            Order.objects.filter(customer=self.request.user.customer)
            .select_related("shipment")
            .prefetch_related("items__product", "mp_payments")
            .order_by("-created_at")[:100]
        )
