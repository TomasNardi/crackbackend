"""
Mercado Pago service helpers
============================
Encapsula la creación de preferencias y la consulta de pagos para mantener
el flujo de checkout trazable y centralizado.
"""

from decimal import Decimal
from urllib.parse import urlencode, urlparse

import mercadopago
from django.conf import settings


class MercadoPagoServiceError(Exception):
    pass


def _normalize_base_url(raw_url: str, fallback: str) -> str:
    """Normaliza URL base y aplica fallback seguro si es invalida."""
    candidate = (raw_url or fallback or "").strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    parsed_fallback = urlparse(fallback)
    return f"{parsed_fallback.scheme}://{parsed_fallback.netloc}"


def _is_public_callback(url: str) -> bool:
    """Mercado Pago suele rechazar auto_return con callbacks locales."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not parsed.scheme or not parsed.netloc:
        return False
    if host in ("localhost", "127.0.0.1"):
        return False
    return not host.endswith(".local")


def _sdk():
    token = getattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "")
    if not token:
        raise MercadoPagoServiceError("MERCADOPAGO_ACCESS_TOKEN no configurado.")
    return mercadopago.SDK(token)


def create_checkout_preference(order, frontend_url_override: str = ""):
    """Crea una preferencia de Checkout Pro para una orden pendiente."""
    sdk = _sdk()

    configured_frontend = getattr(settings, "FRONTEND_URL", "") or "http://localhost:3000"
    forced_return_frontend = getattr(settings, "MERCADOPAGO_FRONTEND_RETURN_URL", "") or ""
    effective_frontend = forced_return_frontend or frontend_url_override or configured_frontend
    frontend_url = _normalize_base_url(effective_frontend, "http://localhost:3000")
    backend_url = _normalize_base_url(
        getattr(settings, "BACKEND_PUBLIC_URL", "") or "http://localhost:8000",
        "http://localhost:8000",
    )

    return_qs = urlencode(
        {
            "code": order.order_code,
            "order": order.id,
            "email": order.customer_email,
        }
    )
    success_url = f"{frontend_url}/checkout/confirmacion?{return_qs}"
    failure_url = f"{frontend_url}/checkout/error?{return_qs}"
    pending_url = f"{frontend_url}/checkout/pendiente?{return_qs}"

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
            "success": success_url,
            "failure": failure_url,
            "pending": pending_url,
        },
        "statement_descriptor": "CRACK TCG",
        "metadata": {
            "order_id": order.id,
            "order_code": order.order_code,
            "shipping_type": order.shipping_type,
        },
    }

    if _is_public_callback(success_url):
        payload["auto_return"] = "approved"

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
