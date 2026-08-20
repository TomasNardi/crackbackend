"""
Reserva de stock para órdenes de pago manual
============================================

Una compra por efectivo, transferencia o crypto no se cobra en el momento: el
cliente tiene que transferir o pasar por el local. Hasta que eso pase, la carta
no puede seguir a la venta —si no, la vendés dos veces— pero tampoco está
vendida.

Ese punto intermedio es la reserva: `Product.reserved_quantity` sube, el stock
real no se toca y la publicación sale de la vidriera si no queda nada
disponible. Después pasa una de dos cosas:

  - Cobrás  → `consume_order_stock`: la reserva se convierte en venta.
  - No paga → `release_order_stock`: la reserva vuelve al stock y se puede vender.

`Order.stock_status` recuerda en cuál de esos pasos quedó cada orden, así
marcarla pagada dos veces no descuenta dos veces, y "Regresar al stock" sobre
una orden ya devuelta no infla el inventario.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.orders.models import Order
from apps.products.models import Product

logger = logging.getLogger(__name__)


def _write(product, *, stock_delta=0, reserved_delta=0):
    """
    Aplica el movimiento y deja `in_stock` coherente, sin pasar por save().

    Se evita `Product.save()` a propósito: recalcula slug e imagen del catálogo,
    que no tienen nada que ver con vender una unidad.
    """
    if product.stock_quantity is None:
        # Sin cantidad cargada es stock sin límite (sellados, accesorios): no
        # hay nada que reservar ni que descontar.
        return

    stock = max(0, product.stock_quantity + stock_delta)
    reserved = max(0, (product.reserved_quantity or 0) + reserved_delta)
    # Reservar más de lo que hay no tiene sentido: el tope es el stock real.
    reserved = min(reserved, stock)
    available = stock - reserved
    now = timezone.now()

    Product.objects.filter(pk=product.pk).update(
        stock_quantity=stock,
        reserved_quantity=reserved,
        in_stock=available > 0,
        updated_at=now,
    )
    product.stock_quantity = stock
    product.reserved_quantity = reserved
    product.in_stock = available > 0
    product.updated_at = now


def _locked_items(order):
    """Ítems de la orden con sus productos bloqueados para evitar carreras."""
    items = list(order.items.select_related("product").all())
    product_ids = [item.product_id for item in items if item.product_id]
    if not product_ids:
        return []

    products = {
        p.id: p
        for p in Product.objects.select_for_update().filter(id__in=product_ids)
    }
    return [(item, products[item.product_id]) for item in items if item.product_id in products]


def _set_stock_status(order, status):
    order.stock_status = status
    Order.objects.filter(pk=order.pk).update(stock_status=status, updated_at=timezone.now())


@transaction.atomic
def reserve_order_stock(order):
    """Aparta la mercadería de una orden de pago manual. Idempotente."""
    if order.stock_status != Order.STOCK_NONE:
        return False

    for item, product in _locked_items(order):
        _write(product, reserved_delta=item.quantity)

    _set_stock_status(order, Order.STOCK_RESERVED)
    return True


@transaction.atomic
def consume_order_stock(order):
    """
    Convierte la orden en venta: baja el stock de verdad.

    Sirve tanto para una orden reservada que se cobró como para una que nunca
    reservó (Mercado Pago, que descuenta recién al aprobarse el pago).
    """
    if order.stock_status == Order.STOCK_CONSUMED:
        return False

    was_reserved = order.stock_status == Order.STOCK_RESERVED

    for item, product in _locked_items(order):
        _write(
            product,
            stock_delta=-item.quantity,
            reserved_delta=-item.quantity if was_reserved else 0,
        )

    _set_stock_status(order, Order.STOCK_CONSUMED)
    return True


@transaction.atomic
def release_order_stock(order):
    """
    Devuelve la mercadería a la venta.

    Cubre los dos casos: una reserva que venció o se canceló (se libera lo
    apartado) y una orden ya cobrada que se da de baja (se suma de vuelta al
    stock, porque la carta volvió a tus manos).
    """
    if order.stock_status not in {Order.STOCK_RESERVED, Order.STOCK_CONSUMED}:
        return False

    was_reserved = order.stock_status == Order.STOCK_RESERVED

    for item, product in _locked_items(order):
        _write(
            product,
            stock_delta=0 if was_reserved else item.quantity,
            reserved_delta=-item.quantity if was_reserved else 0,
        )

    _set_stock_status(order, Order.STOCK_RELEASED)
    return True
