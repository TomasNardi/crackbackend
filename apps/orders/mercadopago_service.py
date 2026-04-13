"""
Mercado Pago service helpers
============================
Encapsula la creación de preferencias y la consulta de pagos para mantener
el flujo de checkout trazable y centralizado.
"""

from decimal import Decimal

import mercadopago
from django.conf import settings


class MercadoPagoServiceError(Exception):
    pass


def _sdk():
    token = getattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "")
    if not token:
        raise MercadoPagoServiceError("MERCADOPAGO_ACCESS_TOKEN no configurado.")
    return mercadopago.SDK(token)


def create_checkout_preference(order):
    """Crea una preferencia de Checkout Pro para una orden pendiente."""
    sdk = _sdk()

    frontend_url = (getattr(settings, "FRONTEND_URL", "") or "http://localhost:3000").rstrip("/")
    backend_url = (getattr(settings, "BACKEND_PUBLIC_URL", "") or "http://localhost:8000").rstrip("/")

    items = [
        {
            "id": str(item.product_id or ""),
            "title": item.product_name,
            "quantity": item.quantity,
            "currency_id": "ARS",
            "unit_price": float(item.unit_price),
        }
        for item in order.items.all()
    ]

    if order.shipping_cost and Decimal(order.shipping_cost) > 0:
        items.append(
            {
                "id": "shipping",
                "title": "Costo de envío",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": float(order.shipping_cost),
            }
        )

    if order.discount_amount and Decimal(order.discount_amount) > 0:
        items.append(
            {
                "id": "discount",
                "title": "Descuento aplicado",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": -float(order.discount_amount),
            }
        )

    payload = {
        "items": items,
        "payer": {
            "name": order.customer_name,
            "email": order.customer_email,
        },
        "external_reference": order.order_code,
        "notification_url": f"{backend_url}/api/v1/payments/webhook/",
        "back_urls": {
            "success": f"{frontend_url}/checkout/confirmacion",
            "failure": f"{frontend_url}/checkout/error",
            "pending": f"{frontend_url}/checkout/confirmacion",
        },
        "auto_return": "approved",
        "statement_descriptor": "CRACK TCG",
        "metadata": {
            "order_id": order.id,
            "order_code": order.order_code,
            "shipping_type": order.shipping_type,
        },
    }

    result = sdk.preference().create(payload)
    response = result.get("response", {})

    if result.get("status") not in (200, 201) or not response.get("id"):
        raise MercadoPagoServiceError(f"No se pudo crear preferencia: {response}")

    return {
        "preference_id": response.get("id"),
        "init_point": response.get("init_point", ""),
        "sandbox_init_point": response.get("sandbox_init_point", ""),
        "raw": response,
    }


def get_payment(payment_id: str):
    """Obtiene el detalle completo de un pago en Mercado Pago."""
    sdk = _sdk()
    result = sdk.payment().get(str(payment_id))
    response = result.get("response", {})

    if result.get("status") not in (200, 201) or not response:
        raise MercadoPagoServiceError(f"No se pudo obtener pago {payment_id}: {response}")

    return response
