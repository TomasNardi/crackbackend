"""
Core Views
===========
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SiteConfig, ExchangeRate, ContactMessage, EmailSubscription, EmailDelivery
from .serializers import (
    SiteConfigSerializer, EmailSubscribeSerializer, ExchangeRateSerializer,
    ContactMessageSerializer, SolicitudVentaSerializer
)
from .emails import send_new_sale_request_notification
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
            serializer.save()
            return Response({"message": "Mensaje recibido. Te respondemos pronto."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
            if from_email and not delivery.from_email:
                delivery.from_email = from_email
            if subject and not delivery.subject:
                delivery.subject = subject

            changed = delivery.apply_event(event_type, event_at, payload, svix_id)
            if changed:
                delivery.save()

        return Response(status=status.HTTP_200_OK)
