"""
Tareas para envío de campañas de email con Resend.
Ejecutadas por Django Q (tareas asincrónicas).
"""

import os
import time
import logging
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from resend import Resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    logger.warning("Resend library not installed")

from .models import EmailCampaign, EmailSubscription


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
    site_url = getattr(django_settings, "SITE_URL", "https://cracktcg.com")
    from_name = "CRACK TCG"

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
                Recibís este email porque te suscribiste a nuestras novedades.<br>
                Este mensaje fue enviado a <span style="color:#C8972E;">{recipient_email}</span>
              </p>
              <p style="margin:0;font-size:11px;color:#d1d5db;">
                © 2025 CRACK TCG · Buenos Aires, Argentina
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
    Actualiza estadísticas en la campaña.
    
    Args:
        campaign_id: ID de la campaña a enviar
    
    Returns:
        dict: Información sobre el envío
    """
    try:
        campaign = EmailCampaign.objects.get(id=campaign_id)
    except EmailCampaign.DoesNotExist:
        logger.error(f"Campaña con ID {campaign_id} no encontrada")
        return {"error": "Campaña no encontrada"}
    
    # Validar que el estado sea 'borrador'
    if campaign.status != 'borrador':
        logger.warning(f"Campaña {campaign_id} en estado '{campaign.get_status_display()}', no se envía")
        return {"error": f"Campaña en estado {campaign.status}"}
    
    # Cambiar estado a 'enviando'
    campaign.status = 'enviando'
    campaign.save(update_fields=["status"])
    
    # Obtener suscriptores activos
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
    
    exitosos = 0
    fallidos = 0
    
    if not RESEND_AVAILABLE:
        logger.error("Resend no está disponible")
        campaign.status = 'cancelado'
        campaign.cantidad_fallidos = len(suscriptores_emails)
        campaign.save()
        return {"error": "Resend service unavailable"}
    
    # Configurar cliente Resend
    api_key = getattr(settings, "RESEND_API_KEY", None)
    from_email = getattr(settings, "RESEND_FROM_EMAIL", "noreply@crackstore.com")
    
    if not api_key:
        logger.error("RESEND_API_KEY no configurado")
        campaign.status = 'cancelado'
        campaign.cantidad_fallidos = len(suscriptores_emails)
        campaign.save()
        return {"error": "API key not configured"}
    
    client = Resend(api_key=api_key)
    
    # Enviar a cada suscriptor
    for i, email in enumerate(suscriptores_emails):
        try:
            html_content = build_campaign_html(campaign, email)
            
            response = client.emails.send(
                **{
                    "from": from_email,
                    "to": email,
                    "subject": campaign.asunto,
                    "html": html_content,
                }
            )
            
            if response.get("id"):
                exitosos += 1
                logger.debug(f"Email enviado a {email} - ID: {response.get('id')}")
            else:
                fallidos += 1
                logger.error(f"Resend devolvió respuesta sin ID para {email}: {response}")
            
            # Rate limiting: ~0.5s entre envíos para no saturar Resend
            if i < len(suscriptores_emails) - 1:
                time.sleep(0.5)
        
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error enviando email a {email}: {error_str}")
            
            # Si es rate limit, reintentar
            if "rate limit" in error_str.lower() or "too many" in error_str.lower():
                logger.info(f"Rate limit detectado. Esperando antes de reintentar {email}...")
                time.sleep(2)
                try:
                    html_content = build_campaign_html(campaign, email)
                    response = client.emails.send(
                        **{
                            "from": from_email,
                            "to": email,
                            "subject": campaign.asunto,
                            "html": html_content,
                        }
                    )
                    if response.get("id"):
                        exitosos += 1
                        logger.info(f"Reintento exitoso para {email}")
                    else:
                        fallidos += 1
                except Exception as retry_error:
                    logger.error(f"Reintento fallido para {email}: {retry_error}")
                    fallidos += 1
            else:
                fallidos += 1
    
    # Actualizar campaña con resultados
    campaign.status = 'enviado'
    campaign.cantidad_enviados = exitosos
    campaign.cantidad_fallidos = fallidos
    campaign.fecha_envio = timezone.now()
    campaign.save()
    
    result = {
        "campaign_id": campaign_id,
        "exitosos": exitosos,
        "fallidos": fallidos,
        "total": len(suscriptores_emails),
    }
    
    logger.info(f"Campaña {campaign_id} completada: {exitosos} enviados, {fallidos} fallidos")
    return result
