"""
Orders Views
=============
"""

import logging
import hashlib
import hmac
from decimal import Decimal
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import SiteConfig
from apps.products.models import Product
from .models import Order, DiscountCode, MercadoPagoPayment
from .serializers import OrderCreateSerializer, OrderReadSerializer
from .emails import send_order_confirmation, send_new_order_notification
from .mercadopago_service import (
    create_checkout_preference,
    get_payment,
    search_payments_by_external_reference,
    MercadoPagoServiceError,
)

logger = logging.getLogger(__name__)


UNIQUE_ORDER_CATEGORIES = {"single", "singles", "slab", "slabs"}


def _send_order_emails(order_id):
    try:
        send_order_confirmation(order_id)
    except Exception as exc:
        logger.error("Error enviando confirmación de orden %s: %s", order_id, exc, exc_info=True)

    try:
        send_new_order_notification(order_id)
    except Exception as exc:
        logger.error("Error enviando notificación de orden %s: %s", order_id, exc, exc_info=True)


def _apply_order_confirmed_side_effects(order):
    """Aplica stock + activación de descuento al confirmar una orden MP como pagada."""
    items = list(order.items.all())
    product_ids = [item.product_id for item in items if item.product_id]

    products = {
        p.id: p
        for p in Product.objects.select_for_update().select_related("category").filter(id__in=product_ids)
    }

    for item in items:
        product = products.get(item.product_id)
        if not product:
            continue

        category_name = product.category.name if product.category else ""
        is_unique = category_name.strip().lower() in UNIQUE_ORDER_CATEGORIES

        if is_unique:
            product.in_stock = False
            product.save(update_fields=["in_stock", "updated_at"])
            continue

        if product.stock_quantity is not None:
            product.stock_quantity = max(0, product.stock_quantity - item.quantity)
            product.in_stock = product.stock_quantity > 0
            product.save(update_fields=["stock_quantity", "in_stock", "updated_at"])

    if order.discount_code:
        discount_code = DiscountCode.objects.select_for_update().filter(code__iexact=order.discount_code).first()
        if discount_code and discount_code.is_valid():
            discount_code.activate()


def _extract_payment_id(data, query_params):
    """Obtiene payment_id desde distintos formatos de notificación MP."""
    payment_id = data.get("data", {}).get("id")
    if not payment_id:
        payment_id = data.get("data.id")
    if not payment_id:
        payment_id = data.get("id")
    if not payment_id:
        payment_id = data.get("payment_id") or data.get("collection_id")
    if not payment_id:
        payment_id = query_params.get("id")
    if not payment_id:
        payment_id = query_params.get("data.id")
    if not payment_id:
        payment_id = query_params.get("payment_id") or query_params.get("collection_id")
    if not payment_id:
        resource = str(data.get("resource") or query_params.get("resource") or "")
        if resource:
            resource_path = urlparse(resource).path.rstrip("/")
            resource_id = resource_path.split("/")[-1] if resource_path else ""
            if resource_id.isdigit():
                payment_id = resource_id
    return str(payment_id) if payment_id else ""


def _extract_mp_topic(data, query_params):
    """Normaliza el tipo de evento MP para aceptar variantes reales del webhook."""
    raw_topic = (
        data.get("type")
        or data.get("topic")
        or data.get("action")
        or query_params.get("type")
        or query_params.get("topic")
        or query_params.get("action")
        or ""
    )
    raw_topic = str(raw_topic).strip().lower()

    if raw_topic.startswith("payment"):
        return "payment"
    if raw_topic == "":
        return "payment"
    return raw_topic


def _get_payment_data_for_validation(payment_id="", external_reference=""):
    """Resuelve el pago final desde MP priorizando payment_id y usando external_reference como fallback."""
    last_error = None
    payment_id = str(payment_id or "").strip()
    external_reference = str(external_reference or "").strip()

    if payment_id:
        try:
            return get_payment(payment_id)
        except MercadoPagoServiceError as exc:
            last_error = exc
            logger.warning("MP get_payment falló para payment_id=%s: %s", payment_id, exc)

    if external_reference:
        try:
            payment_data = search_payments_by_external_reference(external_reference)
            logger.info(
                "MP payment resuelto por external_reference=%s con payment_id=%s status=%s",
                external_reference,
                payment_data.get("id"),
                payment_data.get("status"),
            )
            return payment_data
        except MercadoPagoServiceError as exc:
            last_error = exc
            logger.warning("MP search falló para external_reference=%s: %s", external_reference, exc)

    if last_error:
        raise last_error
    raise MercadoPagoServiceError("Se requiere payment_id o external_reference para validar el pago.")


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
    
    Actualiza tanto el registro MercadoPagoPayment como el estado de la orden.
    """
    payment_id = str(payment_data.get("id") or "")
    external_ref = str(payment_data.get("external_reference") or "")
    payment_status = str(payment_data.get("status") or "")
    payment_method = str(payment_data.get("payment_method_id") or "")
    payment_type = str(payment_data.get("payment_type_id") or "")
    preference_id = str(payment_data.get("metadata", {}).get("preference_id") or "")
    metadata_order_code = str(payment_data.get("metadata", {}).get("order_code") or "")
    metadata_order_id = str(payment_data.get("metadata", {}).get("order_id") or "")
    transaction_amount = Decimal(str(payment_data.get("transaction_amount") or "0"))
    net_received_amount = Decimal(str(payment_data.get("transaction_details", {}).get("net_received_amount") or "0"))
    date_approved_raw = payment_data.get("date_approved")
    date_approved = parse_datetime(date_approved_raw) if date_approved_raw else None

    notify_order_id = None

    with transaction.atomic():
        order = None

        # 1) external_reference del pago (fuente principal)
        if external_ref:
            order = Order.objects.select_for_update().filter(order_code=external_ref).first()

        # 2) metadata.order_code (fallback)
        if not order and metadata_order_code:
            order = Order.objects.select_for_update().filter(order_code=metadata_order_code).first()

        # 3) metadata.order_id (fallback)
        if not order and metadata_order_id.isdigit():
            order = Order.objects.select_for_update().filter(id=int(metadata_order_id)).first()

        # 4) preference_id (fallback)
        if not order and preference_id:
            order = Order.objects.select_for_update().filter(mp_preference_id=preference_id).first()

        # 5) pago ya registrado por payment_id (fallback)
        if not order and payment_id:
            mp_existing = MercadoPagoPayment.objects.select_for_update().filter(payment_id=payment_id).select_related("order").first()
            if mp_existing:
                order = mp_existing.order

        if not order:
            logger.warning(
                "MP %s: orden no encontrada (payment_id=%s, external_reference=%s, metadata_order_code=%s, metadata_order_id=%s, preference_id=%s)",
                source,
                payment_id,
                external_ref,
                metadata_order_code,
                metadata_order_id,
                preference_id,
            )
            return None, False

        if not preference_id:
            preference_id = order.mp_preference_id or payment_id

        mp_payment, _ = MercadoPagoPayment.objects.select_for_update().get_or_create(
            preference_id=preference_id,
            defaults={"order": order},
        )
        if mp_payment.order_id != order.id:
            mp_payment.order = order

        amount_ok = transaction_amount + Decimal("0.01") >= Decimal(order.total)
        ref_ok = (not external_ref) or (external_ref == order.order_code)
        approved = payment_status == "approved"
        final_paid = approved and amount_ok and ref_ok

        mp_payment.payment_id = payment_id
        mp_payment.status = payment_status
        mp_payment.is_paid = final_paid
        mp_payment.payment_method = payment_method
        mp_payment.payment_type = payment_type
        mp_payment.external_reference = external_ref or order.order_code
        mp_payment.transaction_amount = transaction_amount
        mp_payment.net_received_amount = net_received_amount
        mp_payment.date_approved = date_approved
        mp_payment.last_validated_at = timezone.now()
        mp_payment.raw_response = payment_data
        mp_payment.save()

        # Actualizar estado de la orden según el pago
        status_updated = False
        refund_statuses = {"refunded", "charged_back"}
        cancellation_statuses = {"rejected", "cancelled"}

        # Refunded/charged_back debe prevalecer aunque la orden se haya pagado días antes.
        if payment_status in refund_statuses and order.status != Order.STATUS_REFUNDED:
            order.status = Order.STATUS_REFUNDED
            status_updated = True
            logger.info(
                "Orden %s marcada como DEVOLUCIÓN (pago %s: %s)",
                order.order_code,
                payment_id,
                payment_status,
            )
        elif final_paid and order.status not in {Order.STATUS_PAID, Order.STATUS_REFUNDED}:
            order.status = Order.STATUS_PAID
            status_updated = True
            if order.payment_method == Order.PAYMENT_MERCADOPAGO:
                _apply_order_confirmed_side_effects(order)
                notify_order_id = order.id
            logger.info("Orden %s marcada como PAGADA (pago %s aprobado)", order.order_code, payment_id)
        elif payment_status in cancellation_statuses and order.status not in {Order.STATUS_PAID, Order.STATUS_REFUNDED}:
            if order.status != Order.STATUS_CANCELLED:
                order.status = Order.STATUS_CANCELLED
                status_updated = True
            logger.info("Orden %s marcada como CANCELADA (pago %s: %s)", order.order_code, payment_id, payment_status)
        elif payment_status == "pending":
            logger.info("Pago %s en estado pendiente para orden %s (esperando confirmación)", payment_id, order.order_code)
        elif payment_status == "in_process":
            logger.info("Pago %s en proceso para orden %s", payment_id, order.order_code)

        if status_updated:
            order.save(update_fields=["status", "updated_at"])

    if notify_order_id:
        _send_order_emails(notify_order_id)

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

        # Para efectivo la orden queda confirmada en creación. En MP se envía al aprobar el pago.
        if order.payment_method == Order.PAYMENT_CASH:
            _send_order_emails(order.id)

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
        topic = _extract_mp_topic(data, request.query_params)
        payment_id = _extract_payment_id(data, request.query_params)
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

        if not _is_valid_mp_signature(payment_id, x_request_id, x_signature):
            logger.warning("Webhook MP con firma inválida. payment_id=%s", payment_id)
            return Response(status=status.HTTP_200_OK)

        try:
            payment_data = get_payment(payment_id)
            payment_status = payment_data.get("status", "unknown")
            logger.info("Webhook MP recibido: payment_id=%s, topic=%s, status=%s", payment_id, topic, payment_status)
            
            order, paid = _reconcile_payment(payment_data, source="webhook")
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
            payment_data = _get_payment_data_for_validation(
                payment_id=payment_id,
                external_reference=external_reference,
            )
            order, paid = _reconcile_payment(payment_data, source="verify")
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
