"""
Core Views
===========
"""

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.utils import timezone
from django_ratelimit.decorators import ratelimit
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SiteConfig, ExchangeRate, ContactMessage, EmailSubscription, EmailDelivery
from .serializers import (
    SiteConfigSerializer, EmailSubscribeSerializer, ExchangeRateSerializer,
    ContactMessageSerializer, SolicitudVentaSerializer
)
from .contact_tokens import read_mark_read_token
from .emails import (
    send_contact_acknowledgement_email,
    send_contact_notification_email,
    send_new_sale_request_notification,
)
from .newsletter_tokens import read_unsubscribe_token

logger = logging.getLogger(__name__)


class ExchangeRateView(APIView):
    """GET /exchange-rate/ — tipo de cambio USD→ARS actual."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(ExchangeRateSerializer(ExchangeRate.get()).data)


class SiteConfigView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        config = SiteConfig.get()
        return Response(SiteConfigSerializer(config).data)


class EmailSubscribeView(APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True))
    def post(self, request):
        serializer = EmailSubscribeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data["email"]
        subscription, created = EmailSubscription.objects.get_or_create(
            email=email,
            defaults={"is_active": True},
        )

        if created:
            return Response(
                {"message": "Ya estás adentro. Pronto vas a recibir novedades, ingresos y promos de CRACK."},
                status=status.HTTP_201_CREATED,
            )

        if subscription.is_active:
            return Response(
                {"message": "Ya formas parte de la newsletter. Cuando haya novedades, te avisamos por email."},
                status=status.HTTP_200_OK,
            )

        subscription.is_active = True
        subscription.save(update_fields=["is_active"])
        return Response(
            {"message": "Tu suscripción volvió a quedar activa. Vas a recibir nuestras próximas novedades."},
            status=status.HTTP_200_OK,
        )


class EmailUnsubscribeView(APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="10/m", method="POST", block=True))
    def post(self, request):
        token = str(request.data.get("token") or "").strip()
        if not token:
            return Response({"detail": "Token requerido."}, status=status.HTTP_400_BAD_REQUEST)

        email = read_unsubscribe_token(token)
        if not email:
            return Response(
                {"detail": "El enlace de desuscripción es inválido o expiró."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscription = EmailSubscription.objects.filter(email=email).first()
        if not subscription or not subscription.is_active:
            return Response({"message": "Tu email ya estaba desuscripto."}, status=status.HTTP_200_OK)

        subscription.is_active = False
        subscription.save(update_fields=["is_active"])
        return Response({"message": "Ya no recibirás novedades por email."}, status=status.HTTP_200_OK)


class PingView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class ContactView(APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="5/h", method="POST", block=True))
    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        if serializer.is_valid():
            contact = serializer.save()
            try:
                send_contact_notification_email(contact.id)
            except Exception:
                logger.exception("Error enviando notificación de contacto %s", contact.id)
            return Response({"message": "Mensaje recibido. Te respondemos pronto."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ContactMarkReadView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        token = str(request.query_params.get("token") or "").strip()
        token_payload = read_mark_read_token(token)
        if not token_payload:
            return HttpResponse(
                "<h2>Enlace inválido</h2><p>El enlace para marcar el mensaje como leído no es válido.</p>",
                status=400,
            )
        contact_id, recipient_email = token_payload

        is_valid_recipient = NotificationRecipient.objects.filter(
            is_active=True,
            email__iexact=recipient_email,
        ).exists()
        if not is_valid_recipient:
            return HttpResponse(
                "<h2>Acceso denegado</h2><p>El destinatario de este enlace ya no tiene permisos para marcar mensajes.</p>",
                status=403,
            )

        with transaction.atomic():
            contact = ContactMessage.objects.select_for_update().filter(id=contact_id).first()
            if not contact:
                return HttpResponse(
                    "<h2>Mensaje no encontrado</h2><p>El mensaje ya no existe o fue eliminado.</p>",
                    status=404,
                )

            pending_updates = []
            if not contact.read:
                contact.read = True
                contact.read_at = timezone.now()
                contact.read_by_email = recipient_email
                pending_updates.extend(["read", "read_at", "read_by_email"])

            should_send_ack = contact.customer_ack_sent_at is None
            if should_send_ack:
                try:
                    sent = send_contact_acknowledgement_email(contact.id)
                except Exception:
                    sent = False
                    logger.exception("Error enviando acuse de contacto %s", contact.id)

                if sent:
                    contact.customer_ack_sent_at = timezone.now()
                    pending_updates.append("customer_ack_sent_at")

            if pending_updates:
                contact.save(update_fields=pending_updates)

        return HttpResponse(
            "<h2>Mensaje marcado como leído</h2><p>El mensaje fue actualizado en admin y el cliente recibió la confirmación por email.</p>",
            status=200,
        )


class SolicitudVentaCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="5/h", method="POST", block=True))
    def post(self, request):
        serializer = SolicitudVentaSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        solicitud = serializer.save()

        try:
            send_new_sale_request_notification(solicitud.id)
        except Exception:
            logger.exception("Error enviando notificación para la solicitud de venta %s", solicitud.id)

        return Response(
            {
                "message": "Recibimos tu solicitud. Te vamos a contactar pronto.",
                "id": solicitud.id,
            },
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Resend webhook — recibe eventos (sent/delivered/bounced/opened/clicked/...)
# ─────────────────────────────────────────────────────────────────────────────

_SVIX_MAX_AGE_SECONDS = 5 * 60  # rechazar payloads firmados hace > 5 min (anti-replay)
_ORDER_ENTITY_REF_RE = re.compile(r"^order-([A-Z0-9]{6,8})(?:-([a-z0-9_]+))?$", re.IGNORECASE)
_ORDER_CODE_IN_SUBJECT_RE = re.compile(r"\b([A-Z0-9]{6,8})\b")


def _decode_svix_secret(secret: str) -> bytes | None:
    if not secret:
        return None
    cleaned = secret.strip()
    if cleaned.startswith("whsec_"):
        cleaned = cleaned[len("whsec_"):]
    try:
        return base64.b64decode(cleaned)
    except (ValueError, base64.binascii.Error):
        return None


def _verify_svix_signature(raw_body: bytes, svix_id: str, svix_timestamp: str, svix_signature: str, secret: str) -> bool:
    """Verifica firma Svix (HMAC-SHA256). Devuelve True si alguna firma del header matchea."""
    key = _decode_svix_secret(secret)
    if not key or not svix_id or not svix_timestamp or not svix_signature:
        return False

    try:
        ts = int(svix_timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > _SVIX_MAX_AGE_SECONDS:
        return False

    signed_payload = f"{svix_id}.{svix_timestamp}.".encode() + raw_body
    expected = base64.b64encode(hmac.new(key, signed_payload, hashlib.sha256).digest()).decode()

    # El header puede contener varias firmas separadas por espacio: "v1,abc v1,def"
    for entry in svix_signature.split():
        version, _, sig = entry.partition(",")
        if version != "v1":
            continue
        if hmac.compare_digest(expected, sig):
            return True
    return False


def _parse_event_timestamp(value):
    if not value or not isinstance(value, str):
        return None
    try:
        # Resend usa ISO 8601 con sufijo Z
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt_timezone.utc)
    except ValueError:
        return None


def _extract_entity_ref(headers) -> str:
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() == "x-entity-ref-id":
                return str(value or "").strip()

    # Algunos webhooks pueden serializar headers como lista de pares o lista de objetos.
    if isinstance(headers, list):
        for item in headers:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                key = str(item[0] or "").lower()
                if key == "x-entity-ref-id":
                    return str(item[1] or "").strip()
            elif isinstance(item, dict):
                key = str(item.get("key") or item.get("name") or "").lower()
                if key == "x-entity-ref-id":
                    return str(item.get("value") or "").strip()

    if isinstance(headers, str) and "x-entity-ref-id" in headers.lower():
        parts = headers.split(":", 1)
        if len(parts) == 2:
            return parts[1].strip()

    return ""


def _extract_order_code_from_subject(subject: str) -> str:
    subject_value = (subject or "").upper()
    for candidate in _ORDER_CODE_IN_SUBJECT_RE.findall(subject_value):
        return candidate
    return ""


def _collect_code_candidates(*values) -> list[str]:
    """Extrae posibles códigos de orden (6-8 alfanuméricos) desde múltiples textos."""
    found: list[str] = []
    for value in values:
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for candidate in _ORDER_CODE_IN_SUBJECT_RE.findall(text.upper()):
            if candidate not in found:
                found.append(candidate)
    return found


def _extract_order_code_from_entity_ref(entity_ref: str) -> tuple[str, str]:
    """
    Devuelve (order_code, flow_kind) a partir de X-Entity-Ref-ID.
    Formatos soportados:
    - order-ABC123
    - order-ABC123-confirmation
    - order-ABC123-internal_notification
    """
    value = (entity_ref or "").strip()
    if not value:
        return "", ""

    match = _ORDER_ENTITY_REF_RE.match(value)
    if match:
        return (match.group(1) or "").upper(), (match.group(2) or "").lower()

    normalized = value.replace("_", "-")
    parts = normalized.split("-")
    if len(parts) >= 2 and parts[0].lower() == "order":
        code = (parts[1] or "").strip().upper()
        if re.fullmatch(r"[A-Z0-9]{6,8}", code):
            flow_kind = "_".join(part.strip().lower() for part in parts[2:] if part.strip())
            return code, flow_kind

    # Fallback ultra robusto: busca un token tipo código en cualquier segmento.
    for candidate in _collect_code_candidates(value):
        return candidate, ""

    return "", ""


class ResendWebhookView(APIView):
    """POST /api/v1/webhooks/resend/ — recibe eventos firmados de Resend (Svix)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        secret = getattr(settings, "RESEND_WEBHOOK_SECRET", "") or ""
        svix_id = request.headers.get("svix-id", "")
        svix_timestamp = request.headers.get("svix-timestamp", "")
        svix_signature = request.headers.get("svix-signature", "")

        raw_body = request.body or b""

        if not secret:
            logger.error("RESEND_WEBHOOK_SECRET no configurado — rechazando webhook")
            return Response({"detail": "Webhook no configurado."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if not _verify_svix_signature(raw_body, svix_id, svix_timestamp, svix_signature, secret):
            logger.warning("Webhook Resend con firma inválida (svix-id=%s)", svix_id)
            return Response({"detail": "Firma inválida."}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            logger.warning("Webhook Resend con payload no-JSON (svix-id=%s)", svix_id)
            return Response({"detail": "Payload inválido."}, status=status.HTTP_400_BAD_REQUEST)

        event_type = (payload.get("type") or "").strip()
        if event_type not in EmailDelivery.EVENT_MAP:
            logger.info("Webhook Resend con tipo desconocido: %s (svix-id=%s)", event_type, svix_id)
            return Response(status=status.HTTP_200_OK)

        data = payload.get("data") or {}
        email_id = str(data.get("email_id") or "")[:128]
        if not email_id:
            logger.warning("Webhook Resend sin email_id (svix-id=%s)", svix_id)
            return Response(status=status.HTTP_200_OK)

        to_field = data.get("to") or []
        if not isinstance(to_field, list):
            to_field = [to_field]
        recipients = [str(item).strip().lower() for item in to_field if item]
        if not recipients:
            logger.warning("Webhook Resend sin destinatarios (svix-id=%s)", svix_id)
            return Response(status=status.HTTP_200_OK)

        event_at = _parse_event_timestamp(payload.get("created_at") or data.get("created_at"))
        from_email = str(data.get("from") or "")[:255]
        subject = str(data.get("subject") or "")[:512]
        headers = data.get("headers") or {}
        entity_ref = _extract_entity_ref(headers)

        order_code = ""
        flow_kind = ""
        if entity_ref:
            if entity_ref.lower().startswith("campaign-"):
                flow_kind = "campaign"
            else:
                order_code, flow_kind = _extract_order_code_from_entity_ref(entity_ref)

        if not order_code:
            order_code = _extract_order_code_from_subject(subject)

        data_candidates = _collect_code_candidates(
            entity_ref,
            subject,
            data.get("subject"),
            data.get("text"),
            data.get("html"),
            data.get("tags"),
            headers,
        )

        order_obj = None
        if order_code or data_candidates:
            from apps.orders.models import Order

            candidate_codes = []
            if order_code:
                candidate_codes.append(order_code)
            for candidate in data_candidates:
                if candidate not in candidate_codes:
                    candidate_codes.append(candidate)

            for candidate in candidate_codes:
                order_obj = Order.objects.filter(order_code__iexact=candidate).only("id", "order_code").first()
                if order_obj:
                    order_code = order_obj.order_code
                    break

            if not order_obj:
                order_code = ""

        for recipient in recipients:
            delivery, _ = EmailDelivery.objects.get_or_create(
                email_id=email_id,
                to_email=recipient[:512],
                defaults={
                    "from_email": from_email,
                    "subject": subject,
                },
            )
            # Completar metadatos si vinieron vacíos en el primer evento.
            metadata_changed = False
            if from_email and not delivery.from_email:
                delivery.from_email = from_email
                metadata_changed = True
            if subject and not delivery.subject:
                delivery.subject = subject
                metadata_changed = True
            if order_code and delivery.order_code != order_code:
                delivery.order_code = order_code
                metadata_changed = True
            if flow_kind and delivery.flow_kind != flow_kind:
                delivery.flow_kind = flow_kind
                metadata_changed = True
            if order_obj and delivery.order_id != order_obj.id:
                delivery.order = order_obj
                metadata_changed = True

            changed = delivery.apply_event(event_type, event_at, payload, svix_id)
            if changed or metadata_changed:
                delivery.save()

        return Response(status=status.HTTP_200_OK)
