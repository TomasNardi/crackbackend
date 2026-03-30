"""
Emails de órdenes — Resend
===========================
Mientras no haya dominio propio verificado, usamos:
  - from: onboarding@resend.dev  (sandbox de Resend)
  - to:   cracktcg@gmail.com     (hardcodeado para recibir todas las notificaciones)

Cuando tengas tu dominio verificado en Resend, cambiá STORE_EMAIL y FROM_EMAIL
en settings.py y listo.
"""

import logging
import resend
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Configuración ──────────────────────────────────────────────────────────────
# Email fijo de la tienda — recibe copia de TODAS las órdenes
STORE_EMAIL = "cracktcg@gmail.com"

# Remitente — mientras no tengas dominio verificado en Resend usá el sandbox
FROM_EMAIL = getattr(settings, "RESEND_FROM_EMAIL", "onboarding@resend.dev")


def _send(to: list[str], subject: str, html: str) -> bool:
    """Envía un email via Resend. Retorna True si fue exitoso."""
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


# ── Templates ──────────────────────────────────────────────────────────────────

def _order_items_rows(order) -> str:
    rows = ""
    for item in order.items.all():
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0ece4;">{item.product_name}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0ece4;text-align:center;">{item.quantity}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0ece4;text-align:right;font-weight:600;">
            ${item.unit_price:,.0f}
          </td>
        </tr>"""
    return rows


def _base_template(title: str, body: str) -> str:
    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="margin:0;padding:0;background:#f5f1ea;font-family:'Helvetica Neue',Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f1ea;padding:32px 16px;">
        <tr><td align="center">
          <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,0.06);">

            <!-- Header -->
            <tr>
              <td style="background:#1a1a1a;padding:28px 40px;text-align:center;">
                <span style="font-size:26px;font-weight:900;letter-spacing:0.3em;color:#ffffff;">CRACK</span>
                <span style="font-size:26px;font-weight:900;letter-spacing:0.3em;color:#C8972E;">.</span>
              </td>
            </tr>

            <!-- Title -->
            <tr>
              <td style="padding:32px 40px 0;text-align:center;">
                <h1 style="margin:0;font-size:22px;font-weight:800;color:#1a1a1a;letter-spacing:-0.02em;">{title}</h1>
                <div style="width:40px;height:3px;background:#C8972E;margin:12px auto 0;border-radius:2px;"></div>
              </td>
            </tr>

            <!-- Body -->
            <tr><td style="padding:24px 40px 40px;">{body}</td></tr>

            <!-- Footer -->
            <tr>
              <td style="background:#f8f6f2;padding:20px 40px;text-align:center;border-top:1px solid #e8e4dd;">
                <p style="margin:0;font-size:11px;color:#6b6560;letter-spacing:0.1em;">
                  CRACK TCG · cracktcg@gmail.com
                </p>
              </td>
            </tr>

          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """


# ── Emails públicos ────────────────────────────────────────────────────────────

def send_order_confirmation(order_id: int) -> None:
    """Email al cliente confirmando su pedido."""
    from .models import Order
    order = Order.objects.prefetch_related("items").get(id=order_id)
    items_rows = _order_items_rows(order)

    shipping_info = ""
    if order.shipping_type == "home":
        shipping_info = f"""
        <p style="margin:4px 0;font-size:13px;color:#6b6560;">
          📦 Envío a: {order.shipping_address}, {order.shipping_city}, {order.shipping_province}
        </p>"""
    else:
        shipping_info = f"""
        <p style="margin:4px 0;font-size:13px;color:#6b6560;">
          🏪 Retiro en: {order.shipping_branch or 'a coordinar'}
        </p>"""

    discount_row = ""
    if order.discount_amount and order.discount_amount > 0:
        discount_row = f"""
        <tr>
          <td colspan="2" style="padding:6px 12px;text-align:right;color:#16a34a;font-size:13px;">
            Descuento ({order.discount_code})
          </td>
          <td style="padding:6px 12px;text-align:right;color:#16a34a;font-weight:600;">
            -${order.discount_amount:,.0f}
          </td>
        </tr>"""

    body = f"""
    <p style="font-size:15px;color:#1a1a1a;margin:0 0 6px;">
      Hola <strong>{order.customer_name}</strong>,
    </p>
    <p style="font-size:13px;color:#6b6560;margin:0 0 24px;">
      Recibimos tu pedido correctamente. Te contactaremos pronto para coordinar el pago y envío.
    </p>

    <div style="background:#f8f6f2;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
      <p style="margin:0 0 4px;font-size:12px;color:#6b6560;text-transform:uppercase;letter-spacing:0.1em;">
        Pedido #{order.id}
      </p>
      {shipping_info}
    </div>

    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e8e4dd;border-radius:8px;overflow:hidden;margin-bottom:16px;">
      <thead>
        <tr style="background:#f8f6f2;">
          <th style="padding:10px 12px;text-align:left;font-size:11px;color:#6b6560;text-transform:uppercase;letter-spacing:0.1em;">Producto</th>
          <th style="padding:10px 12px;text-align:center;font-size:11px;color:#6b6560;text-transform:uppercase;letter-spacing:0.1em;">Cant.</th>
          <th style="padding:10px 12px;text-align:right;font-size:11px;color:#6b6560;text-transform:uppercase;letter-spacing:0.1em;">Precio</th>
        </tr>
      </thead>
      <tbody>{items_rows}</tbody>
      {discount_row}
      <tfoot>
        <tr style="background:#1a1a1a;">
          <td colspan="2" style="padding:12px;font-weight:800;font-size:14px;color:#ffffff;letter-spacing:0.05em;">TOTAL</td>
          <td style="padding:12px;text-align:right;font-weight:800;font-size:16px;color:#C8972E;">${order.total:,.0f}</td>
        </tr>
      </tfoot>
    </table>

    <p style="font-size:12px;color:#6b6560;margin:0;">
      ¿Preguntas? Respondé este email o escribinos a cracktcg@gmail.com
    </p>
    """

    _send(
        to=[order.customer_email],
        subject=f"✅ Pedido #{order.id} recibido — CRACK TCG",
        html=_base_template(f"¡Pedido #{order.id} confirmado!", body),
    )


def send_new_order_notification(order_id: int) -> None:
    """Notificación interna a la tienda cuando llega un pedido nuevo."""
    from .models import Order
    order = Order.objects.prefetch_related("items").get(id=order_id)
    items_rows = _order_items_rows(order)

    body = f"""
    <div style="background:#fef9f0;border:1px solid #C8972E;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
      <p style="margin:0;font-size:14px;font-weight:700;color:#1a1a1a;">🛒 Nueva orden #{order.id}</p>
    </div>

    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
      <tr>
        <td style="padding:4px 0;font-size:13px;color:#6b6560;width:120px;">Cliente</td>
        <td style="padding:4px 0;font-size:13px;color:#1a1a1a;font-weight:600;">{order.customer_name}</td>
      </tr>
      <tr>
        <td style="padding:4px 0;font-size:13px;color:#6b6560;">Email</td>
        <td style="padding:4px 0;font-size:13px;color:#1a1a1a;">{order.customer_email}</td>
      </tr>
      <tr>
        <td style="padding:4px 0;font-size:13px;color:#6b6560;">Teléfono</td>
        <td style="padding:4px 0;font-size:13px;color:#1a1a1a;">{order.customer_phone or '—'}</td>
      </tr>
      <tr>
        <td style="padding:4px 0;font-size:13px;color:#6b6560;">Envío</td>
        <td style="padding:4px 0;font-size:13px;color:#1a1a1a;">
          {'Domicilio: ' + order.shipping_address + ', ' + order.shipping_city if order.shipping_type == 'home' else 'Retiro: ' + (order.shipping_branch or 'a coordinar')}
        </td>
      </tr>
      {'<tr><td style="padding:4px 0;font-size:13px;color:#6b6560;">Descuento</td><td style="padding:4px 0;font-size:13px;color:#16a34a;">' + order.discount_code + ' (-$' + f"{order.discount_amount:,.0f}" + ')</td></tr>' if order.discount_code else ''}
    </table>

    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e8e4dd;border-radius:8px;overflow:hidden;">
      <thead>
        <tr style="background:#f8f6f2;">
          <th style="padding:10px 12px;text-align:left;font-size:11px;color:#6b6560;text-transform:uppercase;">Producto</th>
          <th style="padding:10px 12px;text-align:center;font-size:11px;color:#6b6560;text-transform:uppercase;">Cant.</th>
          <th style="padding:10px 12px;text-align:right;font-size:11px;color:#6b6560;text-transform:uppercase;">Precio</th>
        </tr>
      </thead>
      <tbody>{items_rows}</tbody>
      <tfoot>
        <tr style="background:#1a1a1a;">
          <td colspan="2" style="padding:12px;font-weight:800;font-size:14px;color:#ffffff;">TOTAL</td>
          <td style="padding:12px;text-align:right;font-weight:800;font-size:16px;color:#C8972E;">${order.total:,.0f}</td>
        </tr>
      </tfoot>
    </table>
    """

    _send(
        to=[STORE_EMAIL],
        subject=f"🛒 Nueva orden #{order.id} — {order.customer_name} (${order.total:,.0f})",
        html=_base_template(f"Nueva orden #{order.id}", body),
    )
