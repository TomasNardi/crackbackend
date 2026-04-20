"""
Orders Views
=============
"""

import logging

from django.conf import settings
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import SiteConfig
from .models import Order, DiscountCode, MercadoPagoPayment
from .serializers import OrderCreateSerializer, OrderReadSerializer
from .mercadopago_service import (
    create_checkout_preference,
    MercadoPagoServiceError,
)
from .services import (
    send_order_emails,
    extract_payment_id,
    extract_mp_topic,
    get_payment_data_for_validation,
    is_valid_mp_signature,
    reconcile_payment,
)

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
        payload = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        frontend_origin = str(payload.pop("frontend_origin", "") or "").strip()

        serializer = self.get_serializer(data=payload)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()

        checkout_payload = None
        if order.payment_method == Order.PAYMENT_MERCADOPAGO:
            try:
                request_origin = frontend_origin or request.headers.get("origin", "")
                pref = create_checkout_preference(order, frontend_url_override=request_origin)
                order.mp_preference_id = pref["preference_id"]
                order.save(update_fields=["mp_preference_id", "updated_at"])

                MercadoPagoPayment.objects.update_or_create(
                    preference_id=pref["preference_id"],
                    defaults={
                        "order": order,
                        "status": "preference_created",
                        "is_paid": False,
                        "raw_response": pref.get("raw", {}),
                    },
                )

                checkout_payload = {
                    "provider": "mercadopago",
                    "public_key": settings.MERCADOPAGO_PUBLIC_KEY,
                    "preference_id": pref["preference_id"],
                    "init_point": pref.get("init_point", ""),
                    "sandbox_init_point": pref.get("sandbox_init_point", ""),
                }
            except MercadoPagoServiceError as exc:
                logger.exception("Error creando preferencia MP para orden %s", order.order_code)
                return Response(
                    {
                        "detail": f"No pudimos iniciar Mercado Pago: {exc}",
                        "order_code": order.order_code,
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        # Para efectivo la orden queda confirmada en creación. En MP se envía al aprobar el pago.
        if order.payment_method == Order.PAYMENT_CASH:
            send_order_emails(order.id)

        return Response(
            {
                "order": OrderReadSerializer(order).data,
                "checkout": checkout_payload,
            },
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
    
    Estados de pago soportados:
    - approved: Pago confirmado
    - pending: Esperando confirmación (ej: transferencia bancaria)
    - rejected: Pago rechazado
    - cancelled: Pago cancelado
    - authorized: Autorizado pero no capturado
    - in_process: En proceso de validación
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = request.data
        topic = extract_mp_topic(data, request.query_params)
        payment_id = extract_payment_id(data, request.query_params)
        x_request_id = request.headers.get("x-request-id") or request.headers.get("X-Request-Id")
        x_signature = request.headers.get("x-signature") or request.headers.get("X-Signature")

        if topic != "payment" or not payment_id:
            logger.warning(
                "Webhook MP ignorado: topic=%s, payment_id=%s, query=%s, body=%s",
                topic,
                payment_id,
                dict(request.query_params),
                data,
            )
            return Response(status=status.HTTP_200_OK)

        if not is_valid_mp_signature(payment_id, x_request_id, x_signature):
            logger.warning("Webhook MP con firma inválida. payment_id=%s", payment_id)
            return Response(status=status.HTTP_200_OK)

        try:
            payment_data = get_payment(payment_id)
            payment_status = payment_data.get("status", "unknown")
            logger.info("Webhook MP recibido: payment_id=%s, topic=%s, status=%s", payment_id, topic, payment_status)
            
            order, paid = reconcile_payment(payment_data, source="webhook")
            if order:
                logger.info("Orden %s actualizada: estado=%s, pagada=%s", order.order_code, order.status, paid)
            else:
                logger.warning("Webhook MP procesado sin orden activa para pago %s", payment_id)

        except Exception as exc:
            logger.exception("Error procesando webhook MP: %s", exc)

        # Siempre 200 para que MP no reintente
        return Response(status=status.HTTP_200_OK)


class MercadoPagoVerifyView(APIView):
    """
    POST /payments/verify/
    Doble validación final desde frontend de confirmación.
    Body: { payment_id, external_reference? }
    """

    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="30/m", method="POST", block=True))
    def post(self, request):
        payment_id = str(request.data.get("payment_id") or "")
        external_reference = str(request.data.get("external_reference") or "")
        if not payment_id and not external_reference:
            return Response(
                {"paid": False, "reason": "missing_payment_id_and_external_reference"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payment_data = get_payment_data_for_validation(
                payment_id=payment_id,
                external_reference=external_reference,
            )
            order, paid = reconcile_payment(payment_data, source="verify")
            if not order:
                return Response(
                    {
                        "paid": False,
                        "reason": "order_not_found",
                        "payment_status": payment_data.get("status", ""),
                        "payment_type": payment_data.get("payment_type_id", ""),
                    },
                    status=status.HTTP_200_OK,
                )

            if external_reference and external_reference != order.order_code:
                return Response({"paid": False, "reason": "external_reference_mismatch"}, status=status.HTTP_200_OK)

            return Response(
                {
                    "paid": paid,
                    "order_code": order.order_code,
                    "order_status": order.status,
                    "payment_status": payment_data.get("status", ""),
                    "payment_type": payment_data.get("payment_type_id", ""),
                },
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            logger.exception("Error en verificación final MP: %s", exc)
            return Response({"paid": False, "reason": "verification_error"}, status=status.HTTP_200_OK)


class PaymentConfigView(APIView):
    """GET /payments/config/ — datos públicos de pago para frontend."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        config = SiteConfig.get()
        return Response(
            {
                "mercadopago_public_key": settings.MERCADOPAGO_PUBLIC_KEY,
                "cash_discount_enabled": config.cash_discount_enabled,
                "cash_discount_percent": float(config.cash_discount_percent),
            },
            status=status.HTTP_200_OK,
        )
