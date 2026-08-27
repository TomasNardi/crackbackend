"""
PDF del pedido de importación.

Reusa el logo y la paleta del comprobante de órdenes para que los dos
documentos se vean como de la misma tienda.
"""

from io import BytesIO

from django.utils import timezone
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.orders.pdf_generator import _get_brand_logo_flowable

PRIMARY_COLOR = HexColor("#C8972E")
TEXT_COLOR = HexColor("#2C1810")
LIGHT_COLOR = HexColor("#F5F1E8")
BORDER_COLOR = HexColor("#D4A574")

STATUS_COLORS = {
    "pending_review": "#e36209",
    "approved": "#2ea44f",
    "rejected": "#d73a49",
    "payment_received": "#0969da",
    "in_argentina": "#8250df",
    "delivered": "#57606a",
    "blocked": "#9a6700",
}


def _usd(value) -> str:
    return f"US$ {value:,.2f}"


def generate_ebay_order_pdf(order) -> BytesIO:
    """Comprobante del pedido. Devuelve el buffer listo para servir."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = getSampleStyleSheet()
    story = []

    # ── Header ──
    header = Table(
        [[
            _get_brand_logo_flowable(styles),
            Paragraph(
                '<font size="12"><b>PEDIDO DE IMPORTACIÓN</b></font>',
                ParagraphStyle("HeaderRight", parent=styles["Normal"],
                               alignment=TA_RIGHT, textColor=TEXT_COLOR),
            ),
        ]],
        colWidths=[3.5 * inch, 3 * inch],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 0.2 * inch))

    divider = Table([[""] * 10], colWidths=[0.63 * inch] * 10)
    divider.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 2, PRIMARY_COLOR)]))
    story.append(divider)
    story.append(Spacer(1, 0.15 * inch))

    # ── Datos del pedido ──
    status_color = STATUS_COLORS.get(order.status, "#666")
    info = Table(
        [[
            Paragraph(
                f"<b>Código:</b> <font color='#C8972E'><b>{order.order_code}</b></font>",
                styles["Normal"],
            ),
            Paragraph(
                f"<b>Fecha:</b> {timezone.localtime(order.created_at).strftime('%d/%m/%Y %H:%M')}",
                styles["Normal"],
            ),
            Paragraph(
                f"<b>Estado:</b> <font color='{status_color}'><b>{order.get_status_display()}</b></font>",
                styles["Normal"],
            ),
        ]],
        colWidths=[2.2 * inch, 2.3 * inch, 2 * inch],
    )
    info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_COLOR),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(info)
    story.append(Spacer(1, 0.2 * inch))

    # ── Cliente y entrega ──
    story.append(Paragraph("<b>CLIENTE</b>", styles["Heading4"]))
    contact = [
        f"<b>Nombre:</b> {order.customer_name}",
        f"<b>Email:</b> {order.customer_email}",
    ]
    if order.customer_phone:
        contact.append(f"<b>Teléfono:</b> {order.customer_phone}")
    contact.append(f"<b>Entrega:</b> {order.delivery_summary}")
    if order.shipping_zip:
        contact.append(f"<b>Código postal:</b> {order.shipping_zip}")
    if order.shipping_branch:
        contact.append(f"<b>Sucursal:</b> {order.shipping_branch}")
    for line in contact:
        story.append(Paragraph(line, styles["Normal"]))

    story.append(Paragraph(
        "<font size='8' color='#888888'>El costo del envío dentro de Argentina no está "
        "incluido en este total: se coordina con la tienda.</font>",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.2 * inch))

    # ── Ítems ──
    story.append(Paragraph("<b>PUBLICACIONES</b>", styles["Heading4"]))
    story.append(Spacer(1, 0.08 * inch))

    cell = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8, leading=10)
    header_cell = ParagraphStyle("HeaderCell", parent=cell, textColor=white, fontSize=8)

    rows = [[
        Paragraph("<b>Publicación</b>", header_cell),
        Paragraph("<b>Cant.</b>", header_cell),
        Paragraph("<b>Unitario</b>", header_cell),
        Paragraph("<b>Total</b>", header_cell),
    ]]

    for item in order.items.all():
        title = item.title if len(item.title) <= 70 else f"{item.title[:67]}..."
        note = ""
        if item.price_changed and item.original_price is not None:
            note = (
                f"<br/><font size='7' color='#d73a49'>Precio actualizado: "
                f"{_usd(item.original_price)} → {_usd(item.price)}</font>"
            )
        rows.append([
            Paragraph(f"{title}{note}", cell),
            Paragraph(str(item.quantity), cell),
            Paragraph(_usd(item.unit_total), cell),
            Paragraph(_usd(item.line_total), cell),
        ])

    items_table = Table(rows, colWidths=[4.2 * inch, 0.6 * inch, 1 * inch, 1 * inch])
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_COLOR]),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 0.2 * inch))

    # ── Totales ──
    totals_rows = [
        ["Precio de las publicaciones", _usd(order.items_total)],
        [f"Comisión ({order.commission_percent:g}%)", _usd(order.commission_total)],
        [f"Tax ({order.tax_percent:g}%)", _usd(order.tax_total)],
        ["Envío eBay", _usd(order.ebay_shipping_total)],
        ["Envío a Argentina", _usd(order.arg_shipping_total)],
        ["TOTAL", _usd(order.total)],
    ]
    totals = Table(totals_rows, colWidths=[2.4 * inch, 1.4 * inch], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEABOVE", (0, -1), (-1, -1), 1, PRIMARY_COLOR),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("TEXTCOLOR", (0, -1), (-1, -1), TEXT_COLOR),
    ]))
    story.append(totals)

    if order.rejection_message:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("<b>MOTIVO DEL RECHAZO</b>", styles["Heading4"]))
        story.append(Paragraph(order.rejection_message, styles["Normal"]))

    if order.block_reason:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("<b>MOTIVO DEL FRENO</b>", styles["Heading4"]))
        story.append(Paragraph(order.block_reason, styles["Normal"]))

    doc.build(story)
    buffer.seek(0)
    return buffer
