"""
Emails de importación eBay — Resend
====================================
Mismo transporte y mismo diseño que los emails de la tienda (fondo oscuro,
dorado #C8972E, logo de la marca). Los templates viven en templates/emails/.

Destinatarios internos: NotificationRecipient (admin → Mail → Destinatarios),
igual que las órdenes normales.
"""

import logging

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
import resend

from apps.ebay.models import EbayConfig, EbayOrder
from apps.ebay.services.order_service import (
    approval_whatsapp_message,
    arrival_whatsapp_message,
    build_whatsapp_url,
    changed_price_items,
)

logger = logging.getLogger(__name__)

FROM_EMAIL = getattr(settings, "RESEND_FROM_EMAIL", "onboarding@resend.dev")


def _send(to: list[str], subject: str, html: str, entity_ref_id: str = "") -> bool:
    api_key = getattr(settings, "RESEND_API_KEY", "")
    if not api_key:
        logger.warning("RESEND_API_KEY no configurada — email no enviado: %s", subject)
        return False

    resend.api_key = api_key
    try:
        payload = {"from": FROM_EMAIL, "to": to, "subject": subject, "html": html}
        if entity_ref_id:
            payload["headers"] = {"X-Entity-Ref-ID": entity_ref_id}
        resend.Emails.send(payload)
        return True
    except Exception as exc:
        logger.exception("Error enviando email '%s': %s", subject, exc)
        return False


def _resolve_public_site_url() -> str:
    for attr in ("FRONTEND_URL", "SITE_URL", "PUBLIC_SITE_URL"):
        value = str(getattr(settings, attr, "") or "").strip()
        if value:
            return value.rstrip("/")
    return "https://cracktcg.com"


def _format_usd(amount) -> str:
    return f"${amount:,.2f}"


def _build_context(order: EbayOrder) -> dict:
    """Contexto común a todos los emails del flujo."""
    site_url = _resolve_public_site_url()
    config = EbayConfig.get()

    items = [
        {
            "title": item.title,
            "image_url": item.image_url,
            "url": item.ebay_url,
            "quantity": item.quantity,
            "unit_total": _format_usd(item.unit_total),
            "line_total": _format_usd(item.line_total),
            "price_changed": item.price_changed,
            "original_price": _format_usd(item.original_price) if item.original_price else None,
            "price": _format_usd(item.price),
        }
        for item in order.items.all()
    ]

    return {
        "order": order,
        "items": items,
        # El bloque de publicaciones y desglose se dibuja salvo que un email lo apague.
        "show_items": True,
        "site_url": site_url,
        "brand_image_url": f"{site_url}/brand/mantenimientofoto.png",
        "tracking_url": f"{site_url}/compra-ebay/orden/{order.order_code}",
        "created_at": timezone.localtime(order.created_at).strftime("%d/%m/%Y %H:%M"),
        "items_total": _format_usd(order.items_total),
        "commission_total": _format_usd(order.commission_total),
        "tax_total": _format_usd(order.tax_total),
        "ebay_shipping_total": _format_usd(order.ebay_shipping_total),
        "arg_shipping_total": _format_usd(order.arg_shipping_total),
        "total": _format_usd(order.total),
        "changed_items": [
            {
                "title": item.title,
                "original_price": _format_usd(item.original_price),
                "price": _format_usd(item.price),
                "went_up": item.price > (item.original_price or item.price),
            }
            for item in changed_price_items(order)
        ],
        "whatsapp_url": f"https://wa.me/{config.whatsapp_number}",
        "config": config,
    }


# ─── Al cliente ───────────────────────────────────────────────────────────────

def send_order_received(order_id: int) -> None:
    """Confirmación de que el pedido entró. Es donde el cliente ve su código."""
    order = EbayOrder.objects.prefetch_related("items").get(id=order_id)
    context = _build_context(order)

    html = render_to_string("emails/ebay_order_received.html", context)
    _send(
        to=[order.customer_email],
        subject=f"Recibimos tu pedido de importación {order.order_code} — CRACK TCG",
        html=html,
        entity_ref_id=f"ebay-{order.order_code}-received",
    )


def send_order_approved(order_id: int) -> None:
    order = EbayOrder.objects.prefetch_related("items").get(id=order_id)
    context = _build_context(order)
    context["whatsapp_url"] = build_whatsapp_url(order, approval_whatsapp_message(order))

    html = render_to_string("emails/ebay_order_approved.html", context)
    _send(
        to=[order.customer_email],
        subject=f"Tu pedido {order.order_code} fue aprobado — CRACK TCG",
        html=html,
        entity_ref_id=f"ebay-{order.order_code}-approved",
    )


def send_order_rejected(order_id: int) -> None:
    order = EbayOrder.objects.prefetch_related("items").get(id=order_id)
    context = _build_context(order)

    html = render_to_string("emails/ebay_order_rejected.html", context)
    _send(
        to=[order.customer_email],
        subject=f"Novedades sobre tu pedido {order.order_code} — CRACK TCG",
        html=html,
        entity_ref_id=f"ebay-{order.order_code}-rejected",
    )


def send_payment_received(order_id: int) -> None:
    """
    Acuse de recibo del pago.

    A propósito no menciona montos: es un comprobante de que el pago llegó, no
    una factura.
    """
    order = EbayOrder.objects.prefetch_related("items").get(id=order_id)
    context = _build_context(order)
    context["show_items"] = False

    html = render_to_string("emails/ebay_order_payment_received.html", context)
    _send(
        to=[order.customer_email],
        subject=f"Recibimos el pago de tu pedido {order.order_code} — CRACK TCG",
        html=html,
        entity_ref_id=f"ebay-{order.order_code}-payment",
    )


def send_order_in_argentina(order_id: int) -> None:
    order = EbayOrder.objects.prefetch_related("items").get(id=order_id)
    context = _build_context(order)
    context["whatsapp_url"] = build_whatsapp_url(order, arrival_whatsapp_message(order))

    html = render_to_string("emails/ebay_order_in_argentina.html", context)
    _send(
        to=[order.customer_email],
        subject=f"Tu pedido {order.order_code} ya está en Argentina — CRACK TCG",
        html=html,
        entity_ref_id=f"ebay-{order.order_code}-arrived",
    )


# ─── Interno ──────────────────────────────────────────────────────────────────

def send_new_order_admin_notification(order_id: int) -> None:
    """Aviso al equipo de que entró un pedido nuevo para revisar."""
    from apps.core.models import NotificationRecipient

    recipients = NotificationRecipient.get_active_emails()
    if not recipients:
        logger.info("Sin destinatarios internos activos — no se envía aviso del pedido eBay %s", order_id)
        return

    order = EbayOrder.objects.prefetch_related("items").get(id=order_id)
    context = _build_context(order)
    context["admin_url"] = f"{str(getattr(settings, 'SITE_URL', '') or '').rstrip('/')}/admin/ebay/ebayorder/{order.id}/change/"

    html = render_to_string("emails/ebay_order_new_admin.html", context)
    _send(
        to=recipients,
        subject=f"Nuevo pedido de importación {order.order_code} — {_format_usd(order.total)}",
        html=html,
        entity_ref_id=f"ebay-{order.order_code}-admin",
    )
