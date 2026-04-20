"""
MercadoPago reconciliation service
==================================
Pure payment/webhook reconciliation helpers extracted from views.
"""

import hashlib
import hmac
import logging
from decimal import Decimal
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.orders.models import Order, MercadoPagoPayment
from apps.orders.mercadopago_service import (
    get_payment,
    search_payments_by_external_reference,
    MercadoPagoServiceError,
)
from .order_confirmation_service import apply_order_confirmed_side_effects, send_order_emails

logger = logging.getLogger(__name__)


def extract_payment_id(data, query_params):
    """Obtain payment_id from different MercadoPago webhook payload formats."""
    payment_id = data.get("data", {}).get("id")
    if not payment_id:
        payment_id = data.get("data.id")
    if not payment_id:
        payment_id = data.get("id")
    if not payment_id:
        payment_id = data.get("payment_id") or data.get("collection_id")
    if not payment_id:
        payment_id = query_params.get("id")
    if not payment_id:
        payment_id = query_params.get("data.id")
    if not payment_id:
        payment_id = query_params.get("payment_id") or query_params.get("collection_id")
    if not payment_id:
        resource = str(data.get("resource") or query_params.get("resource") or "")
        if resource:
            resource_path = urlparse(resource).path.rstrip("/")
            resource_id = resource_path.split("/")[-1] if resource_path else ""
            if resource_id.isdigit():
                payment_id = resource_id
    return str(payment_id) if payment_id else ""


def extract_mp_topic(data, query_params):
    """Normalize MP event type to accept real webhook variants."""
    raw_topic = (
        data.get("type")
        or data.get("topic")
        or data.get("action")
        or query_params.get("type")
        or query_params.get("topic")
        or query_params.get("action")
        or ""
    )
    raw_topic = str(raw_topic).strip().lower()

    if raw_topic.startswith("payment"):
        return "payment"
    if raw_topic == "":
        return "payment"
    return raw_topic


def get_payment_data_for_validation(payment_id="", external_reference=""):
    """Resolve final payment data from MP, using external_reference as fallback."""
    last_error = None
    payment_id = str(payment_id or "").strip()
    external_reference = str(external_reference or "").strip()

    if payment_id:
        try:
            return get_payment(payment_id)
        except MercadoPagoServiceError as exc:
            last_error = exc
            logger.warning("MP get_payment fallo para payment_id=%s: %s", payment_id, exc)

    if external_reference:
        try:
            payment_data = search_payments_by_external_reference(external_reference)
            logger.info(
                "MP payment resuelto por external_reference=%s con payment_id=%s status=%s",
                external_reference,
                payment_data.get("id"),
                payment_data.get("status"),
            )
            return payment_data
        except MercadoPagoServiceError as exc:
            last_error = exc
            logger.warning("MP search fallo para external_reference=%s: %s", external_reference, exc)

    if last_error:
        raise last_error
    raise MercadoPagoServiceError("Se requiere payment_id o external_reference para validar el pago.")


def is_valid_mp_signature(payment_id, x_request_id, x_signature):
    """Validate MP webhook signature using MP_WEBHOOK_SECRET when configured."""
    secret = getattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", "")
    if not secret:
        return True
    if not x_signature:
        return False

    ts = ""
    v1 = ""
    for chunk in str(x_signature).split(","):
        kv = chunk.split("=", 1)
        if len(kv) != 2:
            continue
        key = kv[0].strip()
        value = kv[1].strip()
        if key == "ts":
            ts = value
        elif key == "v1":
            v1 = value

    if not ts or not v1:
        return False

    manifest = []
    if payment_id:
        manifest.append(f"id:{payment_id};")
    if x_request_id:
        manifest.append(f"request-id:{x_request_id};")
    manifest.append(f"ts:{ts};")
    payload = "".join(manifest).encode("utf-8")

    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, v1)


def reconcile_payment(payment_data, source="webhook"):
    """
    Final payment validation and side effects.

    Validates:
    - external_reference matches order_code
    - status is approved
    - transaction_amount covers order total
    """
    payment_id = str(payment_data.get("id") or "")
    external_ref = str(payment_data.get("external_reference") or "")
    payment_status = str(payment_data.get("status") or "")
    payment_method = str(payment_data.get("payment_method_id") or "")
    payment_type = str(payment_data.get("payment_type_id") or "")
    preference_id = str(payment_data.get("metadata", {}).get("preference_id") or "")
    metadata_order_code = str(payment_data.get("metadata", {}).get("order_code") or "")
    metadata_order_id = str(payment_data.get("metadata", {}).get("order_id") or "")
    transaction_amount = Decimal(str(payment_data.get("transaction_amount") or "0"))
    net_received_amount = Decimal(str(payment_data.get("transaction_details", {}).get("net_received_amount") or "0"))
    date_approved_raw = payment_data.get("date_approved")
    date_approved = parse_datetime(date_approved_raw) if date_approved_raw else None

    notify_order_id = None

    with transaction.atomic():
        order = None

        if external_ref:
            order = Order.objects.select_for_update().filter(order_code=external_ref).first()

        if not order and metadata_order_code:
            order = Order.objects.select_for_update().filter(order_code=metadata_order_code).first()

        if not order and metadata_order_id.isdigit():
            order = Order.objects.select_for_update().filter(id=int(metadata_order_id)).first()

        if not order and preference_id:
            order = Order.objects.select_for_update().filter(mp_preference_id=preference_id).first()

        if not order and payment_id:
            mp_existing = MercadoPagoPayment.objects.select_for_update().filter(payment_id=payment_id).select_related("order").first()
            if mp_existing:
                order = mp_existing.order

        if not order:
            logger.warning(
                "MP %s: orden no encontrada (payment_id=%s, external_reference=%s, metadata_order_code=%s, metadata_order_id=%s, preference_id=%s)",
                source,
                payment_id,
                external_ref,
                metadata_order_code,
                metadata_order_id,
                preference_id,
            )
            return None, False

        if not preference_id:
            preference_id = order.mp_preference_id or payment_id

        mp_payment, _ = MercadoPagoPayment.objects.select_for_update().get_or_create(
            preference_id=preference_id,
            defaults={"order": order},
        )
        if mp_payment.order_id != order.id:
            mp_payment.order = order

        amount_ok = transaction_amount + Decimal("0.01") >= Decimal(order.total)
        ref_ok = (not external_ref) or (external_ref == order.order_code)
        approved = payment_status == "approved"
        final_paid = approved and amount_ok and ref_ok

        mp_payment.payment_id = payment_id
        mp_payment.status = payment_status
        mp_payment.is_paid = final_paid
        mp_payment.payment_method = payment_method
        mp_payment.payment_type = payment_type
        mp_payment.external_reference = external_ref or order.order_code
        mp_payment.transaction_amount = transaction_amount
        mp_payment.net_received_amount = net_received_amount
        mp_payment.date_approved = date_approved
        mp_payment.last_validated_at = timezone.now()
        mp_payment.raw_response = payment_data
        mp_payment.save()

        status_updated = False
        refund_statuses = {"refunded", "charged_back"}
        cancellation_statuses = {"rejected", "cancelled"}

        if payment_status in refund_statuses and order.status != Order.STATUS_REFUNDED:
            order.status = Order.STATUS_REFUNDED
            status_updated = True
            logger.info(
                "Orden %s marcada como DEVOLUCION (pago %s: %s)",
                order.order_code,
                payment_id,
                payment_status,
            )
        elif final_paid and order.status not in {Order.STATUS_PAID, Order.STATUS_REFUNDED}:
            order.status = Order.STATUS_PAID
            status_updated = True
            if order.payment_method == Order.PAYMENT_MERCADOPAGO:
                apply_order_confirmed_side_effects(order)
                notify_order_id = order.id
            logger.info("Orden %s marcada como PAGADA (pago %s aprobado)", order.order_code, payment_id)
        elif payment_status in cancellation_statuses and order.status not in {Order.STATUS_PAID, Order.STATUS_REFUNDED}:
            if order.status != Order.STATUS_CANCELLED:
                order.status = Order.STATUS_CANCELLED
                status_updated = True
            logger.info("Orden %s marcada como CANCELADA (pago %s: %s)", order.order_code, payment_id, payment_status)
        elif payment_status == "pending":
            logger.info("Pago %s en estado pendiente para orden %s (esperando confirmacion)", payment_id, order.order_code)
        elif payment_status == "in_process":
            logger.info("Pago %s en proceso para orden %s", payment_id, order.order_code)

        if status_updated:
            order.save(update_fields=["status", "updated_at"])

    if notify_order_id:
        send_order_emails(notify_order_id)

    return order, final_paid
