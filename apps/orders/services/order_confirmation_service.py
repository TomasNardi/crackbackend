"""
Order confirmation service
==========================
Side effects that happen when an order becomes paid.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.products.models import Product
from apps.orders.models import DiscountCode
from apps.orders.emails import send_order_confirmation, send_new_order_notification

logger = logging.getLogger(__name__)

def apply_product_purchase_stock(product, quantity):
    """
    Descuenta las unidades vendidas sin disparar los side effects de save().

    Vale igual para un single que para un sellado: la publicación baja el stock
    y recién se despublica cuando llega a cero. Antes un single se despublicaba
    con la primera venta porque cada copia era un producto aparte; ahora una
    publicación con stock 3 sobrevive a las dos primeras ventas.
    """
    updated_at = timezone.now()

    if product.stock_quantity is None:
        return

    next_stock = max(0, product.stock_quantity - quantity)
    Product.objects.filter(pk=product.pk).update(
        stock_quantity=next_stock,
        in_stock=next_stock > 0,
        updated_at=updated_at,
    )
    product.stock_quantity = next_stock
    product.in_stock = next_stock > 0
    product.updated_at = updated_at


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

        apply_product_purchase_stock(product, item.quantity)

    if order.discount_code:
        discount_code = DiscountCode.objects.select_for_update().filter(code__iexact=order.discount_code).first()
        if discount_code and discount_code.is_valid():
            discount_code.activate()
