"""
Servicio de cotización
=======================
Une el cliente de eBay con la fórmula y con la configuración del admin.

Reglas de negocio que se aplican acá y no en la vista:
  * solo compra directa (FIXED_PRICE) — el precio de una subasta se mueve solo,
    cotizarla sería mentirle al cliente;
  * solo publicaciones en USD — todo el pedido se maneja en dólares;
  * publicación agotada o dada de baja frena el pedido, con el motivo guardado.
"""

import logging
from decimal import Decimal

from apps.ebay.models import EbayConfig, money
from apps.ebay.services.ebay_client import (
    EbayError,
    EbayItemUnavailable,
    extract_item_id,
    get_item,
)
from apps.ebay.services.pricing import build_breakdown

logger = logging.getLogger(__name__)


class QuoteRejected(EbayError):
    """La publicación se pudo leer pero no la podemos cotizar."""

    def __init__(self, message: str, code: str = "quote_rejected"):
        super().__init__(message, code=code)


def _validate_item(item: dict) -> None:
    if not item.get("available", True):
        raise EbayItemUnavailable()

    buying_option = str(item.get("buying_option", "") or "").upper()
    buying_options = [str(o).upper() for o in (item.get("buying_options") or [])]
    if buying_option and buying_option != "FIXED_PRICE" and "FIXED_PRICE" not in buying_options:
        raise QuoteRejected(
            "Esa publicación es una subasta. Por ahora solo cotizamos compras directas "
            "(Buy It Now), porque el precio de una subasta cambia hasta que cierra.",
            code="auction_not_supported",
        )

    currency = str(item.get("currency", "") or "USD").upper()
    if currency != "USD":
        raise QuoteRejected(
            f"Esa publicación está en {currency}. Por ahora solo cotizamos publicaciones en dólares.",
            code="currency_not_supported",
        )

    if Decimal(item.get("price") or 0) <= 0:
        raise QuoteRejected("No pudimos leer el precio de esa publicación.", code="no_price")


def quote_item(
    raw_url: str,
    quantity: int = 1,
    *,
    use_cache: bool = True,
    config: EbayConfig | None = None,
) -> dict:
    """
    Link → cotización completa lista para serializar.

    El envío a Argentina es un valor único: no importa si la publicación es una
    carta suelta, una calificada o un producto sellado.

    `use_cache=False` fuerza la consulta a eBay: se usa al confirmar el pedido,
    donde el precio tiene que ser el de este segundo y no el de hace media hora.
    """
    config = config or EbayConfig.get()

    quantity = max(1, min(int(quantity or 1), int(config.max_quantity_per_item)))

    item = get_item(extract_item_id(raw_url), use_cache=use_cache)
    _validate_item(item)

    breakdown = build_breakdown(
        price=item["price"],
        ebay_shipping=item["shipping"],
        arg_shipping=config.arg_shipping,
        commission_percent=config.commission_percent,
        tax_percent=config.tax_percent,
        quantity=quantity,
    )

    return {
        "item": {
            "item_id": item["item_id"],
            "title": item["title"],
            "image_url": item["image_url"],
            "url": item["item_web_url"],
            "currency": item["currency"],
            "condition": item.get("condition", ""),
            "seller": item.get("seller", ""),
            "has_shipping_info": item.get("has_shipping_info", True),
            "is_mock": item.get("is_mock", False),
        },
        "quote": breakdown,
    }


def requote_for_order(
    *,
    url: str,
    quantity: int,
    expected_price: Decimal | None,
    config: EbayConfig,
) -> dict:
    """
    Re-cotiza una línea al confirmar el pedido, sin cache.

    Si el precio se movió respecto de lo que vio el cliente, no frena nada:
    devuelve el valor real marcado como cambiado, y el aviso viaja al email y
    al admin. Lo único que frena el pedido es que la publicación ya no esté.
    """
    quoted = quote_item(url, quantity, use_cache=False, config=config)

    current_price = quoted["quote"]["price"]
    price_changed = expected_price is not None and money(expected_price) != current_price

    quoted["price_changed"] = price_changed
    quoted["original_price"] = money(expected_price) if price_changed else None
    return quoted
