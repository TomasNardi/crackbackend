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
    content = (campaign.contenido or "").replace("{{email}}", recipient_email)
    image_html = ""
    if campaign.imagen_url:
        image_html = (
            f'<img src="{campaign.imagen_url}" alt="Imagen campaña" '
            'style="display:block;max-width:100%;height:auto;border-radius:8px;margin:0 0 16px 0;">'
        )

    return f"""
        <div style="font-family:Arial,Helvetica,sans-serif;line-height:1.5;color:#111827;">
            {image_html}
            <div>{content}</div>
        </div>
    """


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
