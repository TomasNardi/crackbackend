"""
Vistas de importación eBay
===========================
  GET  /ebay/config/          → parámetros para dibujar la calculadora
  POST /ebay/quote/           → cotiza un link
  POST /ebay/orders/          → confirma el pedido (re-cotiza en el servidor)
  GET  /ebay/orders/<code>/   → seguimiento público
"""

import logging

from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ebay.models import EbayConfig, EbayOrder
from apps.ebay.serializers import (
    EbayConfigSerializer,
    EbayOrderCreateSerializer,
    EbayOrderPublicSerializer,
    QuoteRequestSerializer,
)
from apps.ebay.services.ebay_client import EbayError
from apps.ebay.services.order_service import OrderBlocked, create_order
from apps.ebay.services.quote_service import quote_item
from apps.ebay import tasks

logger = logging.getLogger(__name__)


class EbayConfigView(APIView):
    """Config pública de la sección. Sin datos sensibles."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(EbayConfigSerializer(EbayConfig.get()).data)


@method_decorator(
    ratelimit(key="ip", rate="60/h", method="POST", block=True), name="post",
)
class EbayQuoteView(APIView):
    """
    Cotiza una publicación.

    Tiene rate limit propio porque cada llamada consume cuota de la Browse API:
    sin tope, un solo visitante impaciente puede agotar el día.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        config = EbayConfig.get()
        if not config.is_active:
            return Response(
                {"detail": "La cotización de importaciones está pausada por el momento.",
                 "code": "section_inactive"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = QuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = quote_item(data["url"], data["quantity"], config=config)
        except EbayError as exc:
            return Response(
                {"detail": exc.message, "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(result)


@method_decorator(
    ratelimit(key="ip", rate="10/h", method="POST", block=True), name="post",
)
class EbayOrderCreateView(APIView):
    """Confirma el pedido. Los precios se recalculan acá, nunca se toman del front."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        if not EbayConfig.get().is_active:
            return Response(
                {"detail": "La sección de importaciones está pausada por el momento.",
                 "code": "section_inactive"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = EbayOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = create_order(dict(serializer.validated_data))
        except OrderBlocked as exc:
            # 409: el pedido no se creó porque algo cambió en eBay. El front usa
            # `item_index` para señalar cuál de las publicaciones falló.
            return Response(
                {
                    "detail": exc.message,
                    "code": "order_blocked",
                    "item_index": exc.item_index,
                    "order_code": exc.order.order_code if exc.order else None,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except EbayError as exc:
            return Response(
                {"detail": exc.message, "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tasks.enqueue("send_order_received_task", order.id)
        tasks.enqueue("send_new_order_admin_notification_task", order.id)

        return Response(
            EbayOrderPublicSerializer(order).data, status=status.HTTP_201_CREATED,
        )


class EbayOrderDetailView(APIView):
    """
    Seguimiento por código.

    Devuelve la vista reducida del pedido: sin email, teléfono ni domicilio
    exacto, porque el código es lo único que hace falta para consultarlo.
    """

    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="60/h", method="GET", block=True))
    def get(self, request, order_code: str):
        order = (
            EbayOrder.objects
            .filter(order_code__iexact=(order_code or "").strip())
            .exclude(status=EbayOrder.STATUS_BLOCKED)
            .prefetch_related("items")
            .first()
        )
        if not order:
            return Response(
                {"detail": "No encontramos ningún pedido con ese código.", "code": "not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(EbayOrderPublicSerializer(order).data)
