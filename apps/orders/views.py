"""
Orders Views
=============
"""

import logging

from django.conf import settings
from django.utils import timezone
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from django_q.tasks import async_task
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Order, DiscountCode, MercadoPagoPayment
from .serializers import OrderCreateSerializer, OrderReadSerializer

logger = logging.getLogger(__name__)


class OrderViewSet(viewsets.ModelViewSet):
    """
    - POST /orders/       → crear orden (público — cualquier visitante puede comprar)
    - GET  /orders/       → listar órdenes (solo admin)
    - GET  /orders/{id}/  → detalle (solo admin)
    """

    def get_queryset(self):
        return Order.objects.prefetch_related("items").order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        return OrderReadSerializer

    def get_permissions(self):
        if self.action == "create":
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]

    @method_decorator(ratelimit(key="ip", rate="10/h", method="POST", block=True))
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()

        # Activar código de descuento si se usó uno
        discount_code = order.discount_code
        if discount_code:
            dc = DiscountCode.objects.filter(code__iexact=discount_code).first()
            if dc:
                dc.activate()

        # Enviar emails de forma asíncrona (no bloquea la respuesta)
        async_task('apps.orders.emails.send_order_confirmation', order.id)
        async_task('apps.orders.emails.send_new_order_notification', order.id)

        return Response(
            OrderReadSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )


class ValidateDiscountView(APIView):
    """
    POST /payments/validate-discount/
    Body: { "code": "ABC123" }

    Valida un código de descuento sin revelar si existe o no (anti-enumeración).
    """

    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True))
    def post(self, request):
        code = (request.data.get("code") or "").strip()

        if not code:
            return Response({"valid": False}, status=status.HTTP_200_OK)

        dc = DiscountCode.objects.filter(code__iexact=code).first()

        # Si no existe, respuesta genérica (evita enumeración de códigos)
        if not dc:
            logger.warning("Discount code not found: %s", code)
            return Response({"valid": False}, status=status.HTTP_200_OK)

        if not dc.is_valid():
            reason = "used" if dc.used else "expired"
            return Response({"valid": False, "reason": reason}, status=status.HTTP_200_OK)

        data: dict = {"valid": True, "code": dc.code.upper(), "type": dc.discount_type}
        if dc.discount_type == DiscountCode.DISCOUNT_PERCENT:
            data["amount"] = int(dc.discount_amount)
        else:
            data["amount"] = float(dc.discount_amount)

        return Response(data, status=status.HTTP_200_OK)


class MercadoPagoWebhookView(APIView):
    """
    POST /payments/webhook/
    Recibe notificaciones de MercadoPago y actualiza el estado de la orden.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = request.data
        topic = data.get("type") or request.query_params.get("topic")
        resource_id = data.get("data", {}).get("id") or request.query_params.get("id")

        if topic != "payment" or not resource_id:
            return Response(status=status.HTTP_200_OK)

        try:
            import mercadopago
            sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
            payment_info = sdk.payment().get(resource_id)
            payment_data = payment_info.get("response", {})

            external_ref = payment_data.get("external_reference")
            mp_status = payment_data.get("status")

            if not external_ref:
                return Response(status=status.HTTP_200_OK)

            order = Order.objects.filter(id=external_ref).first()
            if not order:
                logger.warning("MP webhook: orden %s no encontrada", external_ref)
                return Response(status=status.HTTP_200_OK)

            # Actualizar o crear registro de pago
            mp_payment, _ = MercadoPagoPayment.objects.get_or_create(
                preference_id=payment_data.get("order", {}).get("id", resource_id),
                defaults={"order": order},
            )
            mp_payment.payment_id = str(resource_id)
            mp_payment.status = mp_status
            mp_payment.is_paid = mp_status == "approved"
            mp_payment.payment_method = payment_data.get("payment_method_id", "")
            mp_payment.payment_type = payment_data.get("payment_type_id", "")
            mp_payment.raw_response = payment_data
            mp_payment.save()

            if mp_status == "approved":
                order.status = Order.STATUS_PAID
                order.save(update_fields=["status", "updated_at"])

        except Exception as exc:
            logger.exception("Error procesando webhook MP: %s", exc)

        # Siempre 200 para que MP no reintente
        return Response(status=status.HTTP_200_OK)
