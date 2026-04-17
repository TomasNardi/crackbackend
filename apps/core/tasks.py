"""
Tareas para envío de campañas de email con Resend.
Ejecutadas por Django Q (tareas asincrónicas).
"""

import time
import logging
from urllib.parse import quote
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

import resend as resend_lib

from .models import EmailCampaign, EmailSubscription
from .newsletter_tokens import make_unsubscribe_token


def build_campaign_html(campaign, recipient_email):
    """Construye HTML final del correo, aplicando variables e imagen opcional."""
    return _build_preview_html(
        asunto=campaign.asunto or "",
        contenido=campaign.contenido or "",
        imagen_url=campaign.imagen_url or "",
        recipient_email=recipient_email,
    )


def _build_preview_html(asunto, contenido, imagen_url, recipient_email="suscriptor@ejemplo.com"):
    """
    Genera el HTML completo del email tal como lo recibirá el suscriptor.
    Usado tanto para el envío real como para el preview en vivo del admin.
    """
    content = contenido.replace("{{email}}", recipient_email)

    image_block = ""
    if imagen_url and imagen_url.strip():
        image_block = f"""
        <tr>
          <td style="padding:0 0 24px 0;">
            <img src="{imagen_url}" alt="Imagen de campaña"
                 style="display:block;width:100%;max-width:600px;height:auto;border-radius:8px;">
          </td>
        </tr>"""

    from django.conf import settings as django_settings
    frontend_url = str(getattr(django_settings, "FRONTEND_URL", "") or "").strip()
    if not frontend_url.startswith("http"):
      frontend_url = str(getattr(django_settings, "SITE_URL", "https://cracktcg.com") or "").strip()
    site_url = frontend_url or "https://cracktcg.com"
    from_name = "CRACK TCG"
    unsubscribe_token = make_unsubscribe_token(recipient_email)
    unsubscribe_url = f"{site_url.rstrip('/')}/desuscribirse?token={quote(unsubscribe_token)}"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>{asunto}</title>
  <!--[if mso]>
  <noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript>
  <![endif]-->
  <style>
    @media only screen and (max-width: 620px) {{
      .email-container {{ width: 100% !important; }}
      .content-padding {{ padding: 24px 16px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f4f1eb;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">

  <!-- Preheader invisible -->
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">
    {asunto} — CRACK TCG
  </div>

  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color:#f4f1eb;padding:32px 16px;">
    <tr>
      <td align="center">

        <!-- Contenedor principal -->
        <table class="email-container" role="presentation" cellpadding="0" cellspacing="0"
               width="600" style="max-width:600px;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08);">

          <!-- HEADER -->
          <tr>
            <td style="background:linear-gradient(135deg,#1a1a1a 0%,#2d2d2d 100%);padding:32px 40px;text-align:center;">
              <p style="margin:0 0 4px 0;font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:#C8972E;font-weight:600;">CRACK TCG</p>
              <h1 style="margin:0;font-size:22px;font-weight:800;color:#ffffff;letter-spacing:-.02em;line-height:1.3;">
                {asunto}
              </h1>
            </td>
          </tr>

          <!-- BODY -->
          <tr>
            <td class="content-padding" style="padding:36px 40px;">
              <table role="presentation" cellpadding="0" cellspacing="0" width="100%">

                {image_block}

                <!-- Contenido del editor -->
                <tr>
                  <td style="font-size:15px;line-height:1.7;color:#374151;">
                    {content}
                  </td>
                </tr>

                <!-- CTA -->
                <tr>
                  <td style="padding:32px 0 8px 0;text-align:center;">
                    <a href="{site_url}"
                       style="display:inline-block;background-color:#C8972E;color:#ffffff;text-decoration:none;
                              padding:14px 36px;border-radius:8px;font-size:14px;font-weight:700;
                              letter-spacing:.04em;text-transform:uppercase;">
                      Ver tienda →
                    </a>
                  </td>
                </tr>

              </table>
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td style="background-color:#f9f7f3;border-top:1px solid #e8e4dd;padding:24px 40px;text-align:center;">
              <p style="margin:0 0 8px 0;font-size:13px;font-weight:700;color:#1a1a1a;letter-spacing:.05em;">CRACK TCG</p>
              <p style="margin:0 0 12px 0;font-size:12px;color:#9ca3af;line-height:1.5;">
                Recibís este email porque te suscribiste a nuestras novedades.
              </p>
              <p style="margin:0 0 14px 0;">
                <a href="{unsubscribe_url}"
                   style="display:inline-block;background:#ffffff;color:#374151;text-decoration:none;
                          border:1px solid #d1d5db;border-radius:999px;padding:8px 18px;
                          font-size:11px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;">
                  Dejar de recibir novedades
                </a>
              </p>
              <p style="margin:0;font-size:11px;color:#d1d5db;">
                © 2026 CRACK TCG · Deheza 2921, PB, Saavedra, Buenos Aires, Argentina
              </p>
            </td>
          </tr>

        </table>
        <!-- /Contenedor principal -->

      </td>
    </tr>
  </table>

</body>
</html>"""


def send_email_campaign(campaign_id):
    """
    Envía una campaña de email a todos los suscriptores activos.
    Se ejecuta de forma asincrónica via Django Q.
    """
    try:
        campaign = EmailCampaign.objects.get(id=campaign_id)
    except EmailCampaign.DoesNotExist:
        logger.error(f"Campaña con ID {campaign_id} no encontrada")
        return {"error": "Campaña no encontrada"}

    if campaign.status != 'borrador':
        logger.warning(f"Campaña {campaign_id} en estado '{campaign.get_status_display()}', no se envía")
        return {"error": f"Campaña en estado {campaign.status}"}

    campaign.status = 'enviando'
    campaign.save(update_fields=["status"])

    suscriptores_emails = list(
        EmailSubscription.objects.filter(
            is_active=True,
            email__isnull=False
        ).values_list('email', flat=True)
    )

    if not suscriptores_emails:
        campaign.status = 'cancelado'
        campaign.cantidad_enviados = 0
        campaign.cantidad_fallidos = 0
        campaign.save()
        logger.warning(f"Campaña {campaign_id} cancelada: No hay suscriptores activos")
        return {"error": "No hay suscriptores activos"}

    logger.info(f"Iniciando envío de campaña {campaign_id} a {len(suscriptores_emails)} suscriptores")

    api_key   = getattr(settings, "RESEND_API_KEY", None)
    from_email = getattr(settings, "RESEND_FROM_EMAIL", "noreply@cracktcg.com")

    if not api_key:
        campaign.status = 'cancelado'
        campaign.save()
        logger.error("RESEND_API_KEY no configurado")
        return {"error": "API key not configured"}

    # Configurar API key — mismo patrón que DeltaBackend
    resend_lib.api_key = api_key

    exitosos = 0
    fallidos  = 0
    total     = len(suscriptores_emails)

    for i, email in enumerate(suscriptores_emails):
        try:
            html_content = _build_preview_html(
                asunto=campaign.asunto or "",
                contenido=campaign.contenido or "",
                imagen_url=campaign.imagen_url or "",
                recipient_email=email,
            )

            response = resend_lib.Emails.send({
                "from": from_email,
                "to": [email],
                "subject": campaign.asunto,
                "html": html_content,
                "headers": {
                    "Precedence": "bulk",
                    "X-Entity-Ref-ID": f"campaign-{campaign_id}-{email}",
                },
            })

            if response.get("id"):
                exitosos += 1
                logger.debug(f"Email enviado a {email} — ID: {response.get('id')}")
            else:
                fallidos += 1
                logger.error(f"Resend sin ID para {email}: {response}")

            if i < total - 1:
                time.sleep(0.5)

        except Exception as e:
            error_str = str(e)
            logger.error(f"Error enviando a {email}: {error_str}")

            if "rate limit" in error_str.lower() or "too many" in error_str.lower():
                logger.info(f"Rate limit — reintentando {email} en 2s...")
                time.sleep(2)
                try:
                    html_content = _build_preview_html(
                        asunto=campaign.asunto or "",
                        contenido=campaign.contenido or "",
                        imagen_url=campaign.imagen_url or "",
                        recipient_email=email,
                    )
                    response = resend_lib.Emails.send({
                        "from": from_email,
                        "to": [email],
                        "subject": campaign.asunto,
                        "html": html_content,
                    })
                    if response.get("id"):
                        exitosos += 1
                        logger.info(f"Reintento exitoso para {email}")
                    else:
                        fallidos += 1
                except Exception as retry_err:
                    logger.error(f"Reintento fallido para {email}: {retry_err}")
                    fallidos += 1
            else:
                fallidos += 1

    campaign.status = 'enviado'
    campaign.cantidad_enviados = exitosos
    campaign.cantidad_fallidos = fallidos
    campaign.fecha_envio = timezone.now()
    campaign.save()

    result = {
        "campaign_id": campaign_id,
        "exitosos": exitosos,
        "fallidos": fallidos,
        "total": total,
    }
    logger.info(f"Campaña {campaign_id} completada: {exitosos} enviados, {fallidos} fallidos")
    return result
