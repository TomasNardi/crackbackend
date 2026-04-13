"""
Generador de PDFs para órdenes de CRACK TCG.
"""

from io import BytesIO
from datetime import datetime
from decimal import Decimal

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white, grey
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT, TA_JUSTIFY


# Colores de CRACK TCG (Gold/Brown palette)
PRIMARY_COLOR = HexColor("#C8972E")  # Gold
SECONDARY_COLOR = HexColor("#8B6914")  # Dark gold
LIGHT_COLOR = HexColor("#F5F1E8")  # Beige
TEXT_COLOR = HexColor("#2C1810")  # Dark brown
BORDER_COLOR = HexColor("#D4A574")  # Light gold


def generate_order_pdf(order):
    """
    Genera un PDF con el resumen de la orden.
    
    Args:
        order: Instancia del modelo Order
        
    Returns:
        BytesIO: Buffer con el PDF generado
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # ==================== HEADER ====================
    header_data = [
        [
            Paragraph(
                '<font size="28" color="#C8972E"><b>CRACK TCG</b></font>',
                styles["Normal"],
            ),
            Paragraph(
                f'<font size="12" color="#666"><b>COMPROBANTE DE ORDEN</b></font>',
                ParagraphStyle(
                    "HeaderRight",
                    parent=styles["Normal"],
                    alignment=TA_RIGHT,
                    textColor=TEXT_COLOR,
                ),
            ),
        ]
    ]
    
    header_table = Table(header_data, colWidths=[3.5 * inch, 3 * inch])
    header_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.2 * inch))
    
    # ==================== LÍNEA DIVISORIA ====================
    line_data = [["" for _ in range(10)]]
    line_table = Table(line_data, colWidths=[0.63 * inch] * 10)
    line_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 2, PRIMARY_COLOR),
    ]))
    story.append(line_table)
    story.append(Spacer(1, 0.15 * inch))
    
    # ==================== DATOS DE LA ORDEN ====================
    status_color = {
        "pending": "#FF9800",
        "paid": "#4CAF50",
        "cancelled": "#F44336",
    }.get(order.status, "#666")
    
    order_info_data = [
        [
            Paragraph(f"<b>Código de Orden:</b> <font color='#C8972E'><b>{order.order_code}</b></font>", styles["Normal"]),
            Paragraph(f"<b>Fecha:</b> {order.created_at.strftime('%d/%m/%Y %H:%M')}", styles["Normal"]),
            Paragraph(f"<b>Estado:</b> <font color='{status_color}'><b>{order.get_status_display()}</b></font>", styles["Normal"]),
        ]
    ]
    
    order_info_table = Table(order_info_data, colWidths=[2.2 * inch, 2.2 * inch, 2.2 * inch])
    order_info_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ]))
    story.append(order_info_table)
    story.append(Spacer(1, 0.2 * inch))
    
    # ==================== DATOS DEL CLIENTE ====================
    story.append(Paragraph("<b style='color: #2C1810; font-size: 12px;'>DATOS DEL CLIENTE</b>", styles["Normal"]))
    story.append(Spacer(1, 0.08 * inch))
    
    client_data = [
        [
            Paragraph(f"<b>Nombre:</b> {order.customer_name}", styles["Normal"]),
            Paragraph(f"<b>Email:</b> {order.customer_email}", styles["Normal"]),
        ],
        [
            Paragraph(f"<b>Teléfono:</b> {order.customer_phone or '—'}", styles["Normal"]),
            Paragraph(f"<b>Método de Pago:</b> {order.get_payment_method_display()}", styles["Normal"]),
        ],
    ]
    
    client_table = Table(client_data, colWidths=[3.25 * inch, 3.25 * inch])
    client_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 1, BORDER_COLOR),
    ]))
    story.append(client_table)
    story.append(Spacer(1, 0.2 * inch))
    
    # ==================== PRODUCTOS (TABLA) ====================
    story.append(Paragraph("<b style='color: #2C1810; font-size: 12px;'>PRODUCTOS</b>", styles["Normal"]))
    story.append(Spacer(1, 0.08 * inch))
    
    product_data = [
        [
            Paragraph("<b>Producto</b>", styles["Normal"]),
            Paragraph("<b>Precio Unit.</b>", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
            Paragraph("<b>Cantidad</b>", ParagraphStyle("Center", parent=styles["Normal"], alignment=TA_CENTER)),
            Paragraph("<b>Subtotal</b>", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
        ]
    ]
    
    for item in order.items.all():
        subtotal = item.unit_price * item.quantity
        product_data.append([
            Paragraph(item.product_name, styles["Normal"]),
            Paragraph(f"${item.unit_price:.2f}", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
            Paragraph(str(item.quantity), ParagraphStyle("Center", parent=styles["Normal"], alignment=TA_CENTER)),
            Paragraph(f"${subtotal:.2f}", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
        ])
    
    product_table = Table(product_data, colWidths=[3 * inch, 1.2 * inch, 1 * inch, 1.3 * inch])
    product_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY_COLOR),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_COLOR]),
        ("GRID", (0, 0), (-1, -1), 1, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(product_table)
    story.append(Spacer(1, 0.2 * inch))
    
    # ==================== TOTALES ====================
    totals_data = []
    
    # Subtotal
    totals_data.append([
        Paragraph("<b>Subtotal:</b>", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
        Paragraph(f"${order.subtotal:.2f}", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
    ])
    
    # Descuento código
    if order.discount_code:
        totals_data.append([
            Paragraph(f"<b>Descuento ({order.discount_code}):</b>", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
            Paragraph(f"-${order.discount_amount:.2f}", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT, textColor=HexColor("#4CAF50"))),
        ])
    
    # Descuento efectivo
    if order.cash_discount_amount > 0:
        totals_data.append([
            Paragraph("<b>Descuento Efectivo:</b>", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
            Paragraph(f"-${order.cash_discount_amount:.2f}", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT, textColor=HexColor("#4CAF50"))),
        ])
    
    # Envío
    if order.shipping_cost > 0:
        totals_data.append([
            Paragraph(f"<b>Envío:</b>", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
            Paragraph(f"${order.shipping_cost:.2f}", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
        ])
    
    # TOTAL (resaltado)
    totals_data.append([
        Paragraph("<b style='font-size: 12px; color: #C8972E;'>TOTAL:</b>", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
        Paragraph(f"<b style='font-size: 12px; color: #C8972E;'>${order.total:.2f}</b>", ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)),
    ])
    
    totals_table = Table(totals_data, colWidths=[4 * inch, 2.5 * inch])
    totals_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -2), 9),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ("LEFTPADDING", (1, 0), (1, -1), 0),
        ("LINEABOVE", (0, -1), (-1, -1), 2, PRIMARY_COLOR),
        ("BACKGROUND", (0, -1), (-1, -1), LIGHT_COLOR),
        ("TOPPADDING", (0, -1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 0.2 * inch))
    
    # ==================== INFORMACIÓN DE ENVÍO ====================
    story.append(Paragraph("<b style='color: #2C1810; font-size: 12px;'>INFORMACIÓN DE ENVÍO</b>", styles["Normal"]))
    story.append(Spacer(1, 0.08 * inch))
    
    shipping_type_text = order.get_shipping_type_display()
    shipping_address_text = order.shipping_address or "Por confirmar"
    
    if order.shipping_type == "pickup":
        shipping_info = f"<b>Tipo:</b> {shipping_type_text}"
        if order.shipping_branch:
            shipping_info += f"<br/><b>Sucursal:</b> {order.shipping_branch}"
    else:
        shipping_info = f"""
        <b>Tipo:</b> {shipping_type_text}<br/>
        <b>Dirección:</b> {shipping_address_text}<br/>
        <b>Ciudad:</b> {order.shipping_city or '—'}<br/>
        <b>Provincia:</b> {order.shipping_province or '—'}<br/>
        <b>Código Postal:</b> {order.shipping_zip or '—'}
        """
        if order.paqar_tracking_number:
            shipping_info += f"<br/><b>Tracking (Paq.ar):</b> {order.paqar_tracking_number}"
    
    shipping_table_data = [[Paragraph(shipping_info, styles["Normal"])]]
    shipping_table = Table(shipping_table_data, colWidths=[6.5 * inch])
    shipping_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_COLOR),
        ("GRID", (0, 0), (-1, -1), 1, BORDER_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(shipping_table)
    story.append(Spacer(1, 0.25 * inch))
    
    # ==================== PIE DE PÁGINA ====================
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=8,
        textColor=grey,
    )
    story.append(Paragraph(
        "Gracias por tu compra en CRACK TCG.<br/>Si tienes dudas, contactanos a nuestro email o teléfono.",
        footer_style
    ))
    
    # Generar PDF
    doc.build(story)
    buffer.seek(0)
    return buffer
