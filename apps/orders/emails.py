"""
Emails de órdenes — Resend
===========================
Los templates HTML viven en:
  templates/emails/order_confirmation.html
  templates/emails/new_order_notification.html

Remitente:
  - Sandbox:    onboarding@resend.dev  (sin dominio verificado)
  - Producción: RESEND_FROM_EMAIL en variables de entorno de Render

Destinatarios internos: NotificationRecipient (CRUD en admin → Mail → Destinatarios)
"""

import logging
from decimal import Decimal
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
import resend

from apps.orders.services.shipping_carriers import get_carrier_label, get_carrier_tracking_url

logger = logging.getLogger(__name__)

def get_internal_notification_recipients() -> list[str]:
    """Destinatarios activos cargados en el admin (Mail → Destinatarios)."""
    from apps.core.models import NotificationRecipient

    return NotificationRecipient.get_active_emails()

# Remitente — en sandbox usá onboarding@resend.dev; en producción configurá RESEND_FROM_EMAIL
FROM_EMAIL = getattr(settings, "RESEND_FROM_EMAIL", "onboarding@resend.dev")

MP_STATUS_LABELS = {
    "approved": "Aprobado",
    "authorized": "Autorizado",
    "in_process": "En proceso",
    "pending": "Pendiente",
    "rejected": "Rechazado",
    "cancelled": "Cancelado",
    "refunded": "Devolución",
    "charged_back": "Contracargo",
    "expired": "Checkout vencido",
}

MP_METHOD_LABELS = {
    "account_money": "Dinero en cuenta MP",
    "debit_card": "Tarjeta de débito",
    "credit_card": "Tarjeta de crédito",
    "prepaid_card": "Tarjeta prepaga",
    "ticket": "Pago en efectivo (ticket)",
    "bank_transfer": "Transferencia bancaria",
}

MP_TYPE_LABELS = {
    "account_money": "Dinero en cuenta",
    "debit_card": "Débito",
    "credit_card": "Crédito",
    "prepaid_card": "Prepaga",
    "ticket": "Ticket",
    "bank_transfer": "Transferencia",
}


def _send(to: list[str], subject: str, html: str, entity_ref_id: str = "") -> bool:
    """Envía un email via Resend. Retorna True si fue exitoso."""
    api_key = getattr(settings, "RESEND_API_KEY", "")
    if not api_key:
        logger.warning("RESEND_API_KEY no configurada — email no enviado: %s", subject)
        return False

    resend.api_key = api_key
    try:
        payload = {
            "from": FROM_EMAIL,
            "to": to,
            "subject": subject,
            "html": html,
        }
        if entity_ref_id:
            payload["headers"] = {"X-Entity-Ref-ID": entity_ref_id}

        resend.Emails.send(payload)
        return True
    except Exception as exc:
        logger.exception("Error enviando email '%s': %s", subject, exc)
        return False


def _build_items_context(order) -> list[dict]:
    """Convierte los items de la orden en una lista de dicts con valores ya formateados."""
    items = []
    for item in order.items.all():
        # Buscar el producto original para obtener el precio anterior y el descuento
        product = getattr(item, "product", None)
        price_before = None
        discount_percent = 0
        if product:
            price_before = getattr(product, "price_ars", None)
            discount_percent = getattr(product, "discount_percent", 0)
        # Si no hay producto (borrado), usar el precio actual
        if not price_before:
            price_before = item.unit_price
        items.append({
            "name": item.product_name,
            "qty": item.quantity,
            "price": f"${item.unit_price:,.0f}",
            "price_before": f"${price_before:,.0f}" if price_before and price_before != item.unit_price else None,
            "discount_percent": discount_percent if discount_percent else None,
        })
    return items


def _format_money(amount: Decimal | int | float | None) -> str:
    value = amount if amount is not None else Decimal("0")
    return f"${value:,.0f}"


def _format_datetime(value) -> str | None:
    if not value:
        return None
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")


def _resolve_payment_status(order) -> tuple[str, object | None]:
    """Retorna etiqueta de estado de pago y último pago MP (si aplica)."""
    from .models import Order

    if order.status == Order.STATUS_REFUNDED:
        return "Devolución", None
    if order.status == Order.STATUS_CANCELLED:
        return "Cancelada", None

    if order.payment_method == Order.PAYMENT_CASH:
        if order.status == Order.STATUS_PAID:
            return "Pagada", None
        return "Pendiente", None

    mp_payment = order.mp_payments.order_by("-updated_at", "-created_at").first()
    if not mp_payment:
        return "Sin novedades", None

    status_key = (mp_payment.status or "").strip().lower()
    return MP_STATUS_LABELS.get(status_key, mp_payment.status or "Sin estado"), mp_payment


def _build_order_email_context(order) -> dict:
    """Genera contexto estándar compartido por emails de orden."""
    from .models import DiscountCode, Order
    from .services.shipping_service import get_shipping_method_label

    shipping_method = getattr(order, "shipping_method", "") or ""
    shipping_zone = getattr(order, "shipping_zone", "") or ""
    shipping_price_field = getattr(order, "shipping_price", Decimal("0")) or Decimal("0")
    shipping_cost_field = getattr(order, "shipping_cost", Decimal("0")) or Decimal("0")

    if shipping_price_field > 0:
        shipping_amount = shipping_price_field
    elif shipping_cost_field > 0:
        shipping_amount = shipping_cost_field
    else:
        shipping_amount = shipping_price_field or shipping_cost_field or Decimal("0")

    is_store_pickup = shipping_method == Order.SHIPPING_METHOD_STORE_PICKUP
    has_shipping_charge = shipping_amount > 0
    if is_store_pickup:
        shipping_cost_display = "No aplica (retiro en tienda)"
        shipping_price_display = "Sin costo"
        delivery_mode_label = "Retiro en tienda"
    else:
        shipping_cost_display = _format_money(shipping_amount) if has_shipping_charge else "Gratis"
        shipping_price_display = shipping_cost_display
        delivery_mode_label = (
            "Retiro en sucursal de correo"
            if shipping_method in {Order.SHIPPING_METHOD_BRANCH_NORMAL, Order.SHIPPING_METHOD_BRANCH_EXPRESS}
            else "Envío a domicilio"
        )

    payment_status_display, mp_payment = _resolve_payment_status(order)
    site_url = _resolve_public_site_url()
    is_cash = order.payment_method == Order.PAYMENT_CASH
    is_mp = order.payment_method == Order.PAYMENT_MERCADOPAGO
    payment_method_display = "Efectivo / Transferencia / Crypto" if is_cash else order.get_payment_method_display()

    cash_discount_amount = getattr(order, "cash_discount_amount", Decimal("0")) or Decimal("0")
    cash_discount_percent = getattr(order, "cash_discount_percent", Decimal("0")) or Decimal("0")
    total_discount_amount = getattr(order, "discount_amount", Decimal("0")) or Decimal("0")
    coupon_discount_amount = max(Decimal("0"), total_discount_amount - cash_discount_amount)

    shipment = getattr(order, "shipment", None)
    tracking_code = shipment.tracking_code if shipment and shipment.tracking_code else None

    mp_raw = getattr(mp_payment, "raw_response", {}) or {}
    mp_webhook_topic = (
        mp_raw.get("notification_topic")
        or mp_raw.get("topic")
        or mp_raw.get("type")
        or None
    )
    mp_webhook_action = mp_raw.get("action") or mp_raw.get("event") or None
    mp_status_raw = getattr(mp_payment, "status", "") if mp_payment else ""
    mp_status_detail = mp_raw.get("status_detail") or None

    # Formato para mostrar el código y el valor del descuento
    def format_discount_code(order):
        if order.discount_code:
            if order.discount_type == DiscountCode.DISCOUNT_PERCENT:
                coupon = (
                    DiscountCode.objects.filter(code__iexact=order.discount_code)
                    .only("discount_type", "discount_amount")
                    .first()
                )
                if coupon and coupon.discount_type == DiscountCode.DISCOUNT_PERCENT:
                    return f"Código {order.discount_code} ({coupon.discount_amount:.0f}%)"
                return f"Código {order.discount_code}"
            elif order.discount_type == DiscountCode.DISCOUNT_FIXED:
                return f"Código {order.discount_code} (-{_format_money(coupon_discount_amount)})"
        return None

    return {
        "order": order,
        "items": _build_items_context(order),
        "order_code": order.order_code,
        "created_at": timezone.localtime(order.created_at).strftime("%d/%m/%Y %H:%M"),
        "subtotal": _format_money(order.subtotal),
        "coupon_discount_amount": _format_money(coupon_discount_amount) if coupon_discount_amount else None,
        "coupon_discount_code": format_discount_code(order),
        "cash_discount_amount": _format_money(cash_discount_amount) if cash_discount_amount else None,
        "cash_discount_percent": f"{cash_discount_percent:.0f}%" if cash_discount_percent else None,
        "shipping_price": shipping_price_display,
        "shipping_cost_display": shipping_cost_display,
        "shipping_method_label": get_shipping_method_label(shipping_method, shipping_zone),
        "shipping_type_label": order.get_shipping_type_display(),
        "delivery_mode_label": delivery_mode_label,
        "is_pickup": order.shipping_type == Order.SHIPPING_PICKUP,
        "has_shipping_charge": has_shipping_charge,
        "total": _format_money(order.total),
        "payment_method_display": payment_method_display,
        "payment_status_display": payment_status_display,
        "is_cash_payment": is_cash,
        "is_mercadopago_payment": is_mp,
        "mp_preference_id": getattr(order, "mp_preference_id", "") or None,
        "mp_payment_id": getattr(mp_payment, "payment_id", "") or None,
        "mp_payment_method": getattr(mp_payment, "payment_method", "") or None,
        "mp_payment_method_display": MP_METHOD_LABELS.get(
            (getattr(mp_payment, "payment_method", "") or "").lower(),
            getattr(mp_payment, "payment_method", "") or "No informado",
        ) if mp_payment else "No informado",
        "mp_payment_type": getattr(mp_payment, "payment_type", "") or None,
        "mp_payment_type_display": MP_TYPE_LABELS.get(
            (getattr(mp_payment, "payment_type", "") or "").lower(),
            getattr(mp_payment, "payment_type", "") or "No informado",
        ) if mp_payment else "No informado",
        "mp_status_raw": mp_status_raw or None,
        "mp_status_detail": mp_status_detail,
        "mp_transaction_amount": _format_money(getattr(mp_payment, "transaction_amount", None)) if mp_payment else None,
        "mp_net_received_amount": _format_money(getattr(mp_payment, "net_received_amount", None)) if mp_payment else None,
        "mp_date_approved": _format_datetime(getattr(mp_payment, "date_approved", None)) if mp_payment else None,
        "mp_last_validated_at": _format_datetime(getattr(mp_payment, "last_validated_at", None)) if mp_payment else None,
        "mp_expires_at": _format_datetime(getattr(mp_payment, "expires_at", None)) if mp_payment else None,
        "mp_expired_at": _format_datetime(getattr(mp_payment, "expired_at", None)) if mp_payment else None,
        "mp_webhook_topic": mp_webhook_topic,
        "mp_webhook_action": mp_webhook_action,
        "tracking_code": tracking_code,
        "paqar_status_display": order.get_paqar_status_display() if getattr(order, "paqar_status", "") else None,
        "paqar_tracking_number": getattr(order, "paqar_tracking_number", "") or None,
        "paqar_error": getattr(order, "paqar_error", "") or None,
        "brand_image_url": f"{site_url}/brand/mantenimientofoto.png",
        "whatsapp_url": f"{site_url}/wa",
        "discount_code_display": _format_discount_code(order),
    }


def _format_discount_code(order):
    """Generates a formatted discount code with value."""
    if order.discount_code:
        if order.discount_type == "percent":
            from .models import DiscountCode

            coupon = (
                DiscountCode.objects.filter(code__iexact=order.discount_code)
                .only("discount_type", "discount_amount")
                .first()
            )
            discount_value = f"({coupon.discount_amount:.0f}%)" if coupon else ""
        elif order.discount_amount:
            discount_value = f"(-{_format_money(order.discount_amount)})"
        else:
            discount_value = ""
        return f"Código {order.discount_code} {discount_value}"
    return None


def _resolve_public_site_url() -> str:
    """Resuelve URL pública del frontend para links e imágenes en emails."""
    frontend_url = str(getattr(settings, "FRONTEND_URL", "") or "").strip()
    if frontend_url.startswith("http"):
        return frontend_url.rstrip("/")

    site_url = str(getattr(settings, "SITE_URL", "https://cracktcg.com") or "").strip()
    if site_url.startswith("http"):
        return site_url.rstrip("/")

    return "https://cracktcg.com"


# ── Emails públicos ────────────────────────────────────────────────────────────

def send_order_confirmation(order_id: int) -> None:
    """Email al cliente confirmando su pedido."""
    from .models import Order

    order = Order.objects.prefetch_related("items").get(id=order_id)

    context = _build_order_email_context(order)

    html = render_to_string("emails/order_confirmation.html", context)

    _send(
        to=[order.customer_email],
        subject=f"✅ Pedido {order.order_code} recibido — CRACK TCG",
        html=html,
        entity_ref_id=f"order-{order.order_code}-confirmation",
    )


def send_new_order_notification(order_id: int) -> None:
    """Notificación interna a la tienda cuando llega un pedido nuevo."""
    from .models import Order

    order = Order.objects.prefetch_related("items").get(id=order_id)
    context = _build_order_email_context(order)

    html = render_to_string("emails/new_order_notification.html", context)

    _send(
        to=get_internal_notification_recipients(),
        subject=f"🛒 Nueva orden {order.order_code} — {order.customer_name} (${order.total:,.0f})",
        html=html,
        entity_ref_id=f"order-{order.order_code}-internal_notification",
    )


def send_refund_notification(order_id: int) -> None:
    """Email al cliente notificando devolución de pago de Mercado Pago."""
    from .models import Order

    order = Order.objects.get(id=order_id)
    site_url = _resolve_public_site_url()

    context = {
        "order": order,
        "refund_date": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
        "logo_url": f"{site_url}/brand/logo2.png",
    }

    html = render_to_string("emails/order_refund_notification.html", context)

    _send(
        to=[order.customer_email],
        subject=f"Confirmación de devolución de compra {order.order_code} — CRACK TCG",
        html=html,
        entity_ref_id=f"order-{order.order_code}-refund",
    )


def send_payment_confirmed_email(order_id: int) -> None:
    """Email al cliente cuando el admin confirma manualmente el pago de su orden."""
    from .models import Order

    order = Order.objects.prefetch_related("items").get(id=order_id)
    context = _build_order_email_context(order)

    html = render_to_string("emails/order_payment_confirmed.html", context)

    _send(
        to=[order.customer_email],
        subject=f"✅ Pago confirmado — Pedido {order.order_code} — CRACK TCG",
        html=html,
        entity_ref_id=f"order-{order.order_code}-payment_confirmed",
    )


def send_shipment_notification(order_id: int, tracking_code: str, carrier: str | None = None) -> None:
    """Email al cliente cuando su orden fue despachada."""
    from .models import Order

    order = Order.objects.get(id=order_id)
    site_url = _resolve_public_site_url()

    carrier_value = (carrier or "").strip()
    if not carrier_value:
        shipment = getattr(order, "shipment", None)
        carrier_value = getattr(shipment, "carrier", "")

    carrier_label = get_carrier_label(carrier_value)
    tracking_url = get_carrier_tracking_url(carrier_value)
    tracking_button_label = f"Ir a {carrier_label}" if tracking_url else ""

    context = {
        "order": order,
        "tracking_code": tracking_code,
        "shipping_carrier": carrier_label,
        "tracking_url": tracking_url,
        "tracking_button_label": tracking_button_label,
        "brand_image_url": f"{site_url}/brand/mantenimientofoto.png",
        "whatsapp_url": f"{site_url}/wa",
        "shipped_at": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
    }

    html = render_to_string("emails/order_shipped_notification.html", context)

    _send(
        to=[order.customer_email],
        subject=f"Tu compra está en camino — Pedido {order.order_code}",
        html=html,
        entity_ref_id=f"order-{order.order_code}-shipment",
    )
