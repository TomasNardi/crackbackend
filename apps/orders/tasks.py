import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Order, MercadoPagoPayment
from .emails import send_refund_notification, send_checkout_expired_notification

logger = logging.getLogger(__name__)


def send_refund_notification_task(order_id: int) -> None:
    """Wrapper para cola: envía email de devolución al cliente."""
    send_refund_notification(order_id)


def send_checkout_expired_notification_task(order_id: int) -> None:
    """Wrapper para cola: envía email suave cuando expira el checkout MP."""
    send_checkout_expired_notification(order_id)


def _normalize_mp_datetime(value):
    dt = parse_datetime(str(value or ""))
    if not dt:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _resolve_expires_at(mp_payment):
    if mp_payment.expires_at:
        return mp_payment.expires_at

    raw = mp_payment.raw_response or {}
    raw_expiration = raw.get("expiration_date_to") or raw.get("date_of_expiration")
    raw_expires_at = _normalize_mp_datetime(raw_expiration)
    if raw_expires_at:
        return raw_expires_at

    fallback_minutes = getattr(settings, "MERCADOPAGO_PREFERENCE_EXPIRATION_MINUTES", None)
    if fallback_minutes is None:
        fallback_minutes = int(getattr(settings, "MERCADOPAGO_PREFERENCE_EXPIRATION_HOURS", 24)) * 60
    try:
        fallback_minutes = int(fallback_minutes)
    except (TypeError, ValueError):
        fallback_minutes = 24 * 60
    fallback_minutes = max(1, min(fallback_minutes, 7 * 24 * 60))
    return mp_payment.created_at + timedelta(minutes=fallback_minutes)


def expire_stale_mercadopago_checkouts(batch_size=300):
    """Mark stale checkout-only preferences as expired using real expiration timestamps."""
    now = timezone.now()
    grace_minutes = getattr(settings, "MERCADOPAGO_EXPIRATION_GRACE_MINUTES", 5)
    try:
        grace_minutes = int(grace_minutes)
    except (TypeError, ValueError):
        grace_minutes = 5
    grace_minutes = max(0, min(grace_minutes, 120))
    threshold = now - timedelta(minutes=grace_minutes)

    candidates = (
        MercadoPagoPayment.objects.select_related("order")
        .filter(
            order__payment_method=Order.PAYMENT_MERCADOPAGO,
            order__status=Order.STATUS_PENDING,
            is_paid=False,
        )
        .filter(payment_id="")
        .filter(status__in=["", "preference_created"])
        .order_by("created_at")[: max(1, int(batch_size))]
    )

    processed = 0
    expired = 0
    expired_order_ids = []
    for mp_payment in candidates:
        processed += 1
        expires_at = _resolve_expires_at(mp_payment)
        if not expires_at:
            continue

        if mp_payment.expires_at != expires_at:
            mp_payment.expires_at = expires_at

        if expires_at > threshold:
            mp_payment.save(update_fields=["expires_at", "updated_at"])
            continue

        with transaction.atomic():
            locked_payment = (
                MercadoPagoPayment.objects.select_for_update()
                .select_related("order")
                .filter(pk=mp_payment.pk)
                .first()
            )
            if not locked_payment:
                continue

            locked_order = locked_payment.order
            if (
                locked_order.status != Order.STATUS_PENDING
                or locked_order.payment_method != Order.PAYMENT_MERCADOPAGO
                or locked_payment.is_paid
                or locked_payment.payment_id
                or (locked_payment.status or "") not in {"", "preference_created"}
            ):
                continue

            locked_payment.expires_at = locked_payment.expires_at or expires_at
            locked_payment.status = "expired"
            # Keep admin-facing expiration timestamps aligned.
            locked_payment.expired_at = locked_payment.expires_at
            locked_payment.last_validated_at = now
            locked_payment.save(
                update_fields=["status", "expires_at", "expired_at", "last_validated_at", "updated_at"]
            )

            locked_order.status = Order.STATUS_EXPIRED
            locked_order.save(update_fields=["status", "updated_at"])
            expired += 1
            expired_order_ids.append(locked_order.id)

    if expired:
        logger.info("Sweep MP expiraciones: expiradas=%s procesadas=%s", expired, processed)

    for order_id in expired_order_ids:
        try:
            from django_q.tasks import async_task

            async_task("apps.orders.tasks.send_checkout_expired_notification_task", order_id)
        except Exception as exc:
            logger.warning(
                "No se pudo encolar email de checkout vencido para order_id=%s. Se envia en sync. Error: %s",
                order_id,
                exc,
            )
            send_checkout_expired_notification_task(order_id)

    return {"processed": processed, "expired": expired}
