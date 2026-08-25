"""
Creación del pedido de importación
===================================
Todo pedido se re-cotiza contra eBay antes de guardarse. El front manda links,
tipos y cantidades; los precios los pone este módulo.

Dos desenlaces posibles cuando algo cambió desde que el cliente cotizó:

  * el precio se movió → el pedido se crea con el precio real, la línea queda
    marcada y el aviso viaja al email del cliente y al admin;
  * la publicación se agotó o se dio de baja → el pedido no avanza. Igual se
    guarda como "Frenada" con el motivo, para que el owner vea el intento en
    el historial en vez de perderlo.
"""

import logging
from decimal import Decimal

from django.db import transaction

from apps.ebay.models import EbayConfig, EbayOrder, EbayOrderItem
from apps.ebay.services.ebay_client import EbayError, EbayItemUnavailable
from apps.ebay.services.quote_service import requote_for_order

logger = logging.getLogger(__name__)


class OrderBlocked(Exception):
    """
    El pedido no se pudo confirmar. Trae el pedido ya guardado como
    'Frenada' para que la vista pueda devolver el código junto con el motivo.
    """

    def __init__(self, message: str, order: EbayOrder | None = None, item_index: int | None = None):
        super().__init__(message)
        self.message = message
        self.order = order
        self.item_index = item_index


def create_order(validated_data: dict) -> EbayOrder:
    """
    Crea el pedido a partir de los datos ya validados por el serializer.

    Cotiza todo antes de escribir nada: si una publicación se cayó, el pedido
    frenado tiene que sobrevivir, y no sobreviviría dentro de la transacción
    que guarda el pedido bueno.

    Levanta OrderBlocked si alguna publicación dejó de estar disponible.
    """
    config = EbayConfig.get()
    items_input = validated_data.pop("items")

    quoted_lines = []
    for index, line in enumerate(items_input):
        try:
            quoted_lines.append(requote_for_order(
                url=line["url"],
                quantity=line.get("quantity", 1),
                expected_price=line.get("quoted_price"),
                config=config,
            ))
        except (EbayItemUnavailable, EbayError) as exc:
            # Agotada, subasta, otra moneda o link caído: el pedido no puede
            # seguir, pero el intento queda registrado con el motivo.
            order = _save_blocked(validated_data, config, index, line, exc.message)
            raise OrderBlocked(exc.message, order=order, item_index=index)

    with transaction.atomic():
        order = EbayOrder.objects.create(
            commission_percent=config.commission_percent,
            tax_percent=config.tax_percent,
            **validated_data,
        )

        for quoted in quoted_lines:
            breakdown = quoted["quote"]
            item = quoted["item"]
            EbayOrderItem.objects.create(
                order=order,
                ebay_item_id=item["item_id"],
                ebay_url=item["url"],
                title=item["title"][:500],
                image_url=item["image_url"][:1000],
                quantity=breakdown["quantity"],
                price=breakdown["price"],
                commission=breakdown["commission"],
                tax=breakdown["tax"],
                ebay_shipping=breakdown["ebay_shipping"],
                arg_shipping=breakdown["arg_shipping"],
                price_changed=quoted.get("price_changed", False),
                original_price=quoted.get("original_price"),
            )

        order.recalculate_totals()

    return order


def _save_blocked(
    validated_data: dict, config: EbayConfig, index: int, line: dict, reason: str,
) -> EbayOrder:
    """Registra el intento fallido para que el owner lo vea en el historial."""
    order = EbayOrder.objects.create(
        status=EbayOrder.STATUS_BLOCKED,
        block_reason=f"Publicación {index + 1} ({line.get('url', '')}): {reason}",
        commission_percent=config.commission_percent,
        tax_percent=config.tax_percent,
        **validated_data,
    )
    logger.info("Pedido eBay %s frenado: %s", order.order_code, order.block_reason)
    return order


def changed_price_items(order: EbayOrder) -> list[EbayOrderItem]:
    """Líneas cuyo precio se movió entre la cotización y la confirmación."""
    return [item for item in order.items.all() if item.price_changed]


def build_whatsapp_url(order: EbayOrder, message: str, config: EbayConfig | None = None) -> str:
    """Link wa.me con el mensaje ya cargado, igual que en las órdenes de la tienda."""
    from urllib.parse import quote

    config = config or EbayConfig.get()
    return f"https://wa.me/{config.whatsapp_number}?text={quote(message)}"


def approval_whatsapp_message(order: EbayOrder) -> str:
    return (
        f"Hola CRACKTCG, me contacto por el pedido {order.order_code} de eBay, "
        "que fue aprobado, para coordinar el pago."
    )


def arrival_whatsapp_message(order: EbayOrder) -> str:
    return (
        f"Hola CRACKTCG, me contacto por el pedido {order.order_code} de eBay, "
        "que ya llegó a la tienda, para coordinar el retiro o el envío."
    )
