"""Emails transaccionales del módulo core."""

import logging
from urllib.parse import quote

import resend
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from .contact_tokens import make_mark_read_token
from .models import ContactMessage, NotificationRecipient, SolicitudVenta

logger = logging.getLogger(__name__)

FROM_EMAIL = getattr(settings, "RESEND_FROM_EMAIL", "onboarding@resend.dev")


def _resolve_public_site_url() -> str:
    frontend_url = str(getattr(settings, "FRONTEND_URL", "") or "").strip()
    if frontend_url.startswith("http"):
        return frontend_url.rstrip("/")

    site_url = str(getattr(settings, "SITE_URL", "https://cracktcg.com") or "").strip()
    if site_url.startswith("http"):
        return site_url.rstrip("/")

    return "https://cracktcg.com"


def _resolve_backend_url() -> str:
    backend_url = str(getattr(settings, "BACKEND_PUBLIC_URL", "") or "").strip()
    if not backend_url.startswith("http"):
        backend_url = str(getattr(settings, "SITE_URL", "https://cracktcg.com") or "").strip()
    return (backend_url or "https://cracktcg.com").rstrip("/")


def build_contact_mark_read_url(contact_message_id: int, recipient_email: str) -> str:
    token = make_mark_read_token(contact_message_id, recipient_email)
    return f"{_resolve_backend_url()}/api/v1/contact/mark-read/?token={quote(token)}"


def _send(to: list[str], subject: str, html: str) -> bool:
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


def send_new_sale_request_notification(solicitud_id: int) -> bool:
    solicitud = SolicitudVenta.objects.get(id=solicitud_id)
    destinatarios = NotificationRecipient.get_active_emails()
    if not destinatarios:
        logger.warning("No hay destinatarios activos para notificaciones de solicitudes de venta")
        return False

    context = {
        "solicitud": solicitud,
        "tipo_coleccion": solicitud.get_tipo_coleccion_display(),
        "fecha_creacion": timezone.localtime(solicitud.fecha_creacion).strftime("%d/%m/%Y %H:%M"),
        "imagenes": solicitud.imagenes or [],
    }
    html = render_to_string("emails/sale_request_notification.html", context)
    return _send(destinatarios, "Nueva solicitud de venta", html)


def send_sale_request_status_email(solicitud_id: int) -> bool:
    solicitud = SolicitudVenta.objects.get(id=solicitud_id)

    if solicitud.estado == SolicitudVenta.Estado.RECHAZADO:
        mensaje = (
            "Evaluamos tus productos y agradecemos tu tiempo, actualmente no estamos interesados en avanzar con la compra."
        )
    elif solicitud.estado == SolicitudVenta.Estado.ACEPTADO:
        mensaje = (
            f"Nos pondremos en contacto por WhatsApp mediante el número {solicitud.celular} para avanzar con la compra de tu colección."
        )
    else:
        logger.info("La solicitud %s sigue pendiente; no se envía email al usuario", solicitud.id)
        return False

    context = {
        "solicitud": solicitud,
        "mensaje": mensaje,
        "estado": solicitud.get_estado_display(),
    }
    html = render_to_string("emails/sale_request_status.html", context)
    return _send([solicitud.email], "Actualización de tu solicitud de venta", html)


def send_contact_notification_email(contact_message_id: int) -> bool:
    contact = ContactMessage.objects.get(id=contact_message_id)
    destinatarios = NotificationRecipient.get_active_recipients()
    if not destinatarios:
        logger.warning("No hay destinatarios activos para notificaciones de contacto")
        return False

    site_url = _resolve_public_site_url()
    created_at = timezone.localtime(contact.created_at).strftime("%d/%m/%Y %H:%M")
    sent_count = 0

    for destinatario in destinatarios:
        recipient_email = destinatario["email"]
        recipient_name = destinatario["name"]
        context = {
            "contact": contact,
            "created_at": created_at,
            "mark_read_url": build_contact_mark_read_url(contact.id, recipient_email),
            "brand_image_url": f"{site_url}/brand/logo2.png",
            "recipient_name": recipient_name,
        }
        html = render_to_string("emails/contact_notification_admin.html", context)
        if _send([recipient_email], f"Contacto {contact.name}", html):
            sent_count += 1

    if sent_count == 0:
        logger.warning("No se pudo enviar ninguna notificación de contacto para %s", contact.id)
        return False

    return True


def send_contact_acknowledgement_email(contact_message_id: int) -> bool:
    contact = ContactMessage.objects.get(id=contact_message_id)
    site_url = _resolve_public_site_url()
    context = {
        "contact": contact,
        "brand_image_url": f"{site_url}/brand/logo2.png",
    }
    html = render_to_string("emails/contact_acknowledgement.html", context)
    return _send([contact.email], "Contacto recibido - CRACK TCG", html)