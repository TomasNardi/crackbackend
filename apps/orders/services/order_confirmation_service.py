"""
Order confirmation service
==========================
Side effects that happen when an order becomes paid.
"""

import logging

from apps.orders.models import DiscountCode
from apps.orders.emails import send_order_confirmation, send_new_order_notification
from apps.orders.services.stock_reservation_service import consume_order_stock

logger = logging.getLogger(__name__)


def send_order_emails(order_id):
    """Send customer and internal notifications for an order."""
    try:
        send_order_confirmation(order_id)
    except Exception as exc:
        logger.error("Error enviando confirmacion de orden %s: %s", order_id, exc, exc_info=True)

    try:
        send_new_order_notification(order_id)
    except Exception as exc:
        logger.error("Error enviando notificacion de orden %s: %s", order_id, exc, exc_info=True)


def apply_order_confirmed_side_effects(order):
    """Apply stock and discount activation when an MP order is confirmed as paid."""
    # `consume_order_stock` sabe si la orden venía reservada o no, y no
    # descuenta dos veces si el webhook de Mercado Pago llega repetido.
    consume_order_stock(order)

    if order.discount_code:
        discount_code = DiscountCode.objects.select_for_update().filter(code__iexact=order.discount_code).first()
        if discount_code and discount_code.is_valid():
            discount_code.activate()
