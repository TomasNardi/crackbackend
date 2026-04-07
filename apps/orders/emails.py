"""
Emails de órdenes — Resend
===========================
Los templates HTML viven en:
  templates/emails/order_confirmation.html
  templates/emails/new_order_notification.html

Remitente:
  - Sandbox:    onboarding@resend.dev  (sin dominio verificado)
  - Producción: RESEND_FROM_EMAIL en variables de entorno de Render

Destinatario tienda: STORE_EMAIL (siempre recibe copia de cada orden)
"""

import logging
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
import resend

logger = logging.getLogger(__name__)

# Email fijo de la tienda — recibe copia de TODAS las órdenes
STORE_EMAIL = "cracktcg@gmail.com"

# Remitente — en sandbox usá onboarding@resend.dev; en producción configurá RESEND_FROM_EMAIL
FROM_EMAIL = getattr(settings, "RESEND_FROM_EMAIL", "onboarding@resend.dev")


def _send(to: list[str], subject: str, html: str) -> bool:
    """Envía un email via Resend. Retorna True si fue exitoso."""
    api_key = getattr(settings, "RESEND_API_KEY", "")
    if not api_key:
        logger.warning("RESEND_API_KEY no configurada — email no enviado: %s", subject)
        return False

    resend.api_key = api_key
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to,
            "subject": subject,
            "html": html,
        })
        return True
    except Exception as exc:
        logger.exception("Error enviando email '%s': %s", subject, exc)
        return False


def _build_items_context(order) -> list[dict]:
    """Convierte los items de la orden en una lista de dicts con valores ya formateados."""
    return [
        {
            "name": item.product_name,
            "qty": item.quantity,
            "price": f"${item.unit_price:,.0f}",
        }
        for item in order.items.all()
    ]


# ── Emails públicos ────────────────────────────────────────────────────────────

def send_order_confirmation(order_id: int) -> None:
    """Email al cliente confirmando su pedido."""
    from .models import Order
    order = Order.objects.prefetch_related("items").get(id=order_id)

    context = {
        "order": order,
        "items": _build_items_context(order),
        "total": f"${order.total:,.0f}",
        "discount_amount": f"${order.discount_amount:,.0f}" if order.discount_amount else None,
    }

    html = render_to_string("emails/order_confirmation.html", context)

    _send(
        to=[order.customer_email],
        subject=f"✅ Pedido {order.order_code} recibido — CRACK TCG",
        html=html,
    )


def send_new_order_notification(order_id: int) -> None:
    """Notificación interna a la tienda cuando llega un pedido nuevo."""
    from .models import Order
    order = Order.objects.prefetch_related("items").get(id=order_id)

    context = {
        "order": order,
        "items": _build_items_context(order),
        "total": f"${order.total:,.0f}",
        "discount_amount": f"${order.discount_amount:,.0f}" if order.discount_amount else None,
        "created_at": timezone.localtime(order.created_at).strftime("%d/%m/%Y %H:%M"),
    }

    html = render_to_string("emails/new_order_notification.html", context)

    _send(
        to=[STORE_EMAIL],
        subject=f"🛒 Nueva orden {order.order_code} — {order.customer_name} (${order.total:,.0f})",
        html=html,
    )
