"""
Order confirmation service
==========================
Side effects that happen when an order becomes paid.
"""

import logging
from decimal import Decimal

from django.db import transaction

from apps.products.models import Product
from apps.orders.models import DiscountCode
from apps.orders.emails import send_order_confirmation, send_new_order_notification

logger = logging.getLogger(__name__)

UNIQUE_ORDER_CATEGORIES = {"single", "singles", "slab", "slabs"}


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
