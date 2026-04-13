"""
Orders Views
=============
"""

import logging
import hashlib
import hmac
from decimal import Decimal

from django.conf import settings
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import SiteConfig
from .models import Order, DiscountCode, MercadoPagoPayment
from .serializers import OrderCreateSerializer, OrderReadSerializer
from .emails import send_order_confirmation, send_new_order_notification
from .mercadopago_service import create_checkout_preference, get_payment, MercadoPagoServiceError

logger = logging.getLogger(__name__)


def _extract_payment_id(data, query_params):
    """Obtiene payment_id desde distintos formatos de notificación MP."""
    payment_id = data.get("data", {}).get("id")
    if not payment_id:
        payment_id = data.get("id")
    if not payment_id:
        payment_id = query_params.get("id")
    return str(payment_id) if payment_id else ""


def _is_valid_mp_signature(payment_id, x_request_id, x_signature):
    """Valida la firma webhook de MP usando MP_WEBHOOK_SECRET si está configurado."""
    secret = getattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", "")
    if not secret:
        return True
    if not x_signature:
        return False

    ts = ""
    v1 = ""
    for chunk in str(x_signature).split(","):
        kv = chunk.split("=", 1)
        if len(kv) != 2:
            continue
        key = kv[0].strip()
        value = kv[1].strip()
        if key == "ts":
            ts = value
        elif key == "v1":
            v1 = value

    if not ts or not v1:
        return False

    manifest = []
    if payment_id:
        manifest.append(f"id:{payment_id};")
    if x_request_id:
        manifest.append(f"request-id:{x_request_id};")
    manifest.append(f"ts:{ts};")
    payload = "".join(manifest).encode("utf-8")

    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, v1)


def _reconcile_payment(payment_data, source="webhook"):
    """
    Segunda validación de pago:
    - external_reference debe coincidir con order_code
    - status debe ser approved
    - transaction_amount debe cubrir el total
    """
    payment_id = str(payment_data.get("id") or "")
    external_ref = str(payment_data.get("external_reference") or "")
    payment_status = str(payment_data.get("status") or "")
    payment_method = str(payment_data.get("payment_method_id") or "")
    payment_type = str(payment_data.get("payment_type_id") or "")
    preference_id = str(payment_data.get("metadata", {}).get("preference_id") or "")
    transaction_amount = Decimal(str(payment_data.get("transaction_amount") or "0"))
    net_received_amount = Decimal(str(payment_data.get("transaction_details", {}).get("net_received_amount") or "0"))
    date_approved_raw = payment_data.get("date_approved")
    date_approved = parse_datetime(date_approved_raw) if date_approved_raw else None

    if not external_ref:
        logger.warning("MP %s sin external_reference. payment_id=%s", source, payment_id)
        return None, False

    order = Order.objects.filter(order_code=external_ref).first()
    if not order:
        logger.warning("MP %s: orden no encontrada para external_reference=%s", source, external_ref)
        return None, False

    if not preference_id:
        preference_id = order.mp_preference_id or payment_id

    mp_payment, _ = MercadoPagoPayment.objects.get_or_create(
        preference_id=preference_id,
        defaults={"order": order},
    )
    if mp_payment.order_id != order.id:
        mp_payment.order = order

    amount_ok = transaction_amount + Decimal("0.01") >= Decimal(order.total)
    ref_ok = external_ref == order.order_code
    approved = payment_status == "approved"
    final_paid = approved and amount_ok and ref_ok

    mp_payment.payment_id = payment_id
    mp_payment.status = payment_status
    mp_payment.is_paid = final_paid
    mp_payment.payment_method = payment_method
    mp_payment.payment_type = payment_type
    mp_payment.external_reference = external_ref
    mp_payment.transaction_amount = transaction_amount
    mp_payment.net_received_amount = net_received_amount
    mp_payment.date_approved = date_approved
    mp_payment.last_validated_at = timezone.now()
    mp_payment.raw_response = payment_data
    mp_payment.save()

    if final_paid and order.status != Order.STATUS_PAID:
        order.status = Order.STATUS_PAID
        order.save(update_fields=["status", "updated_at"])

    return order, final_paid


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

        # Enviar emails de forma síncrona (críticos — deben llegar ya)
        try:
            send_order_confirmation(order.id)
        except Exception as e:
            logger.error(f"Error enviando confirmación de orden {order.id}: {e}", exc_info=True)

        try:
            send_new_order_notification(order.id)
        except Exception as e:
            logger.error(f"Error enviando notificación de orden {order.id}: {e}", exc_info=True)

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
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = request.data
        topic = data.get("type") or request.query_params.get("topic") or "payment"
        payment_id = _extract_payment_id(data, request.query_params)
        x_request_id = request.headers.get("x-request-id") or request.headers.get("X-Request-Id")
        x_signature = request.headers.get("x-signature") or request.headers.get("X-Signature")

        if topic != "payment" or not payment_id:
            return Response(status=status.HTTP_200_OK)

        if not _is_valid_mp_signature(payment_id, x_request_id, x_signature):
            logger.warning("Webhook MP con firma inválida. payment_id=%s", payment_id)
            return Response(status=status.HTTP_200_OK)

        try:
            payment_data = get_payment(payment_id)
            _reconcile_payment(payment_data, source="webhook")

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
        if not payment_id:
            return Response({"paid": False, "reason": "missing_payment_id"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment_data = get_payment(payment_id)
            order, paid = _reconcile_payment(payment_data, source="verify")
            if not order:
                return Response({"paid": False, "reason": "order_not_found"}, status=status.HTTP_200_OK)

            external_reference = str(request.data.get("external_reference") or "")
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
