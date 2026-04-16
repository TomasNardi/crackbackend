"""Emails transaccionales del módulo core."""

import logging

import resend
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from .models import ConfiguracionNotificaciones, SolicitudVenta

logger = logging.getLogger(__name__)

FROM_EMAIL = getattr(settings, "RESEND_FROM_EMAIL", "onboarding@resend.dev")


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
    destinatarios = ConfiguracionNotificaciones.get().get_emails_list()
    if not destinatarios:
        logger.warning("No hay emails configurados para notificaciones de solicitudes de venta")
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