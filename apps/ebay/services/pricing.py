"""
Fórmula de la cotización
=========================
Aislada del cliente HTTP y del ORM para poder testearla sola.

    total = precio + comisión% + tax% + envío eBay + envío a Argentina

La comisión y el tax se calculan sobre el precio de la publicación, no sobre el
envío: es lo que hace el competidor y es lo que el owner espera cobrar.
"""

from decimal import Decimal

from apps.ebay.models import money


def percent_of(amount: Decimal, percent: Decimal) -> Decimal:
    return money(Decimal(amount or 0) * Decimal(percent or 0) / Decimal("100"))


def build_breakdown(
    *,
    price: Decimal,
    ebay_shipping: Decimal,
    arg_shipping: Decimal,
    commission_percent: Decimal,
    tax_percent: Decimal,
    quantity: int = 1,
) -> dict:
    """
    Desglose unitario y por línea de una publicación.

    Devuelve Decimals ya redondeados a centavos, de modo que la suma que ve el
    cliente coincida exactamente con la que se guarda en la orden.
    """
    price = money(price)
    ebay_shipping = money(ebay_shipping)
    arg_shipping = money(arg_shipping)
    quantity = max(int(quantity or 1), 1)

    commission = percent_of(price, commission_percent)
    tax = percent_of(price, tax_percent)

    # "Subtotal publicación" en la referencia: lo que sale la carta ya con los
    # fees, antes de sumarle los dos envíos.
    item_with_fees = money(price + commission + tax)
    unit_total = money(item_with_fees + ebay_shipping + arg_shipping)

    return {
        "price": price,
        "commission": commission,
        "tax": tax,
        "item_with_fees": item_with_fees,
        "ebay_shipping": ebay_shipping,
        "arg_shipping": arg_shipping,
        "unit_total": unit_total,
        "quantity": quantity,
        "line_total": money(unit_total * quantity),
        "commission_percent": Decimal(commission_percent or 0),
        "tax_percent": Decimal(tax_percent or 0),
    }


def sum_breakdowns(breakdowns: list[dict]) -> dict:
    """Totales de un carrito completo, respetando la cantidad de cada línea."""

    def total(field: str) -> Decimal:
        return money(sum((b[field] * b["quantity"] for b in breakdowns), Decimal("0")))

    items_total = total("price")
    commission_total = total("commission")
    tax_total = total("tax")
    ebay_shipping_total = total("ebay_shipping")
    arg_shipping_total = total("arg_shipping")

    return {
        "items_total": items_total,
        "commission_total": commission_total,
        "tax_total": tax_total,
        "ebay_shipping_total": ebay_shipping_total,
        "arg_shipping_total": arg_shipping_total,
        "total": money(
            items_total + commission_total + tax_total
            + ebay_shipping_total + arg_shipping_total
        ),
    }
