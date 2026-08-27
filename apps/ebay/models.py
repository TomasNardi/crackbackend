"""
Modelos de importación eBay
============================
Un pedido de importación no tiene nada que ver con una orden de la tienda: no
toca stock, no pasa por MercadoPago y sus ítems son publicaciones de eBay, no
`Product`. Por eso vive en su propia app en vez de colgarse de `orders.Order`.

El ciclo es manual de punta a punta —el owner aprueba, cobra por fuera, importa
y avisa— así que el modelo guarda un timestamp por paso para tener el historial.

Todos los importes de esta app están en USD.
"""

import random
from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.utils import timezone


# Mismo alfabeto que orders.Order: sin 0/O ni 1/I/L, que se confunden dictados
# por teléfono. El código se comparte por WhatsApp, así que importa.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 6

TWO_PLACES = Decimal("0.01")


def money(value) -> Decimal:
    """Redondea a centavos."""
    return Decimal(value or 0).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _generate_order_code() -> str:
    """Código único de 6 caracteres, con reintentos ante colisión."""
    for _ in range(20):
        code = "".join(random.choices(_CODE_ALPHABET, k=_CODE_LENGTH))
        if not EbayOrder.objects.filter(order_code=code).exists():
            return code
    return "".join(random.choices(_CODE_ALPHABET, k=_CODE_LENGTH + 2))


class EbayConfig(models.Model):
    """
    Parámetros de negocio de la calculadora. Singleton editable en el admin —
    la idea es que el owner cambie comisión, tax y envíos sin tocar código.
    """

    is_active = models.BooleanField(
        "Sección activa", default=True,
        help_text="Desactivar para ocultar la calculadora y frenar pedidos nuevos.",
    )

    commission_percent = models.DecimalField(
        "% comisión", max_digits=5, decimal_places=2, default=Decimal("10"),
        help_text="Se aplica sobre el precio de la publicación.",
    )
    tax_percent = models.DecimalField(
        "% tax", max_digits=5, decimal_places=2, default=Decimal("7"),
        help_text="Se aplica sobre el precio de la publicación.",
    )

    arg_shipping = models.DecimalField(
        "Envío a Argentina (USD)", max_digits=10, decimal_places=2, default=Decimal("20"),
        help_text=(
            "Costo de traer una unidad desde el courier en EE.UU. Es único: "
            "aplica igual a cartas sueltas, calificadas y productos sellados."
        ),
    )

    us_zip = models.CharField(
        "ZIP del courier en EE.UU.", max_length=10, default="33122",
        help_text="eBay cotiza el envío contra este código postal. Sin esto no devuelve costo de envío.",
    )
    us_country = models.CharField("País del courier", max_length=2, default="US")
    marketplace_id = models.CharField(
        "Marketplace", max_length=30, default="EBAY_US",
        help_text="Sitio de eBay contra el que se cotiza.",
    )


    quote_ttl_minutes = models.PositiveIntegerField(
        "Validez de la cotización (minutos)", default=60,
        help_text="Pasado este tiempo la cotización guardada en el carrito se vuelve a pedir.",
    )
    max_items_per_order = models.PositiveIntegerField("Máx. ítems por pedido", default=20)
    max_quantity_per_item = models.PositiveIntegerField("Máx. unidades por publicación", default=10)

    whatsapp_number = models.CharField(
        "WhatsApp", max_length=20, default="541150588131",
        help_text="Solo números, con código de país. Se usa en los links wa.me de los emails.",
    )

    intro_text = models.TextField(
        "Texto de la sección", blank=True,
        default="Ingresá el enlace de eBay y conocé el costo final de importación, con todos los gastos incluidos.",
    )

    updated_at = models.DateTimeField("Actualizado", auto_now=True)

    class Meta:
        verbose_name = "Configuración de importación eBay"
        verbose_name_plural = "Configuración de importación eBay"

    def __str__(self):
        return f"Config eBay — comisión {self.commission_percent}% / tax {self.tax_percent}%"

    def save(self, *args, **kwargs):
        # Singleton: siempre PK=1, mismo patrón que core.SiteConfig.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj



class EbayOrder(models.Model):
    """Pedido de importación."""

    STATUS_PENDING = "pending_review"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_PAYMENT_RECEIVED = "payment_received"
    STATUS_IN_ARGENTINA = "in_argentina"
    STATUS_DELIVERED = "delivered"
    STATUS_BLOCKED = "blocked"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pendiente de aprobación"),
        (STATUS_APPROVED, "Aprobada"),
        (STATUS_REJECTED, "Rechazada"),
        (STATUS_PAYMENT_RECEIVED, "Pago recibido"),
        (STATUS_IN_ARGENTINA, "En Argentina"),
        (STATUS_DELIVERED, "Entregada"),
        (STATUS_BLOCKED, "Frenada"),
    ]

    # Estados que siguen su curso normal. `blocked` queda afuera: es el registro
    # de un intento que no prosperó, guardado solo para tener el historial.
    ACTIVE_STATUSES = [
        STATUS_PENDING, STATUS_APPROVED, STATUS_PAYMENT_RECEIVED,
        STATUS_IN_ARGENTINA, STATUS_DELIVERED,
    ]

    DELIVERY_PICKUP = "pickup"
    DELIVERY_HOME = "home"
    DELIVERY_BRANCH = "branch"
    DELIVERY_CHOICES = [
        (DELIVERY_PICKUP, "Retiro en tienda"),
        (DELIVERY_HOME, "Envío a domicilio"),
        (DELIVERY_BRANCH, "Envío a sucursal"),
    ]

    order_code = models.CharField(
        "Código de pedido", max_length=8, unique=True, db_index=True, blank=True,
        help_text="Generado automáticamente. Es lo que el cliente usa para seguir el pedido.",
    )

    # Contacto
    customer_name = models.CharField("Nombre", max_length=255)
    customer_email = models.EmailField("Email")
    customer_phone = models.CharField("Teléfono", max_length=30, blank=True)

    # Entrega — el costo no entra en el total, se coordina por WhatsApp al final.
    delivery_type = models.CharField(
        "Tipo de entrega", max_length=20, choices=DELIVERY_CHOICES, default=DELIVERY_PICKUP,
    )
    shipping_address = models.CharField("Dirección", max_length=255, blank=True)
    shipping_city = models.CharField("Ciudad", max_length=120, blank=True)
    shipping_province = models.CharField("Provincia", max_length=120, blank=True)
    shipping_zip = models.CharField("Código postal", max_length=20, blank=True)
    shipping_branch = models.CharField("Sucursal", max_length=255, blank=True)
    customer_notes = models.TextField("Comentarios del cliente", blank=True)

    status = models.CharField(
        "Estado", max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    rejection_message = models.TextField(
        "Motivo del rechazo", blank=True,
        help_text="Se incluye en el email que recibe el cliente.",
    )
    block_reason = models.TextField(
        "Motivo del freno", blank=True,
        help_text="Por qué no se pudo confirmar el pedido (publicación agotada o caída).",
    )
    admin_notes = models.TextField("Notas internas", blank=True)

    # Snapshot de la config al momento del pedido: si mañana cambia la comisión,
    # los pedidos viejos tienen que seguir mostrando lo que se les cobró.
    commission_percent = models.DecimalField("% comisión aplicado", max_digits=5, decimal_places=2, default=0)
    tax_percent = models.DecimalField("% tax aplicado", max_digits=5, decimal_places=2, default=0)

    # Totales (USD)
    items_total = models.DecimalField("Precio publicaciones", max_digits=12, decimal_places=2, default=0)
    commission_total = models.DecimalField("Comisión", max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField("Tax", max_digits=12, decimal_places=2, default=0)
    ebay_shipping_total = models.DecimalField("Envío eBay", max_digits=12, decimal_places=2, default=0)
    arg_shipping_total = models.DecimalField("Envío a Argentina", max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField("Total", max_digits=12, decimal_places=2, default=0)

    has_price_changes = models.BooleanField(
        "Hubo cambios de precio", default=False,
        help_text="Algún ítem cambió de precio entre la cotización y la confirmación.",
    )

    # Un timestamp por paso — el estado dice dónde está, esto dice cuándo pasó.
    approved_at = models.DateTimeField("Aprobada el", null=True, blank=True)
    rejected_at = models.DateTimeField("Rechazada el", null=True, blank=True)
    payment_received_at = models.DateTimeField("Pago recibido el", null=True, blank=True)
    arrived_at = models.DateTimeField("Llegó a Argentina el", null=True, blank=True)
    delivered_at = models.DateTimeField("Entregada el", null=True, blank=True)

    created_at = models.DateTimeField("Creado", auto_now_add=True)
    updated_at = models.DateTimeField("Actualizado", auto_now=True)

    class Meta:
        verbose_name = "Pedido eBay"
        verbose_name_plural = "Pedidos eBay"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pedido eBay {self.order_code} — {self.customer_name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.order_code:
            self.order_code = _generate_order_code()
        super().save(*args, **kwargs)

    def recalculate_totals(self, commit: bool = True):
        """Recompone los totales desde los ítems ya guardados."""
        items = list(self.items.all())
        self.items_total = money(sum((i.price * i.quantity for i in items), Decimal("0")))
        self.commission_total = money(sum((i.commission * i.quantity for i in items), Decimal("0")))
        self.tax_total = money(sum((i.tax * i.quantity for i in items), Decimal("0")))
        self.ebay_shipping_total = money(sum((i.ebay_shipping * i.quantity for i in items), Decimal("0")))
        self.arg_shipping_total = money(sum((i.arg_shipping * i.quantity for i in items), Decimal("0")))
        self.total = money(
            self.items_total + self.commission_total + self.tax_total
            + self.ebay_shipping_total + self.arg_shipping_total
        )
        self.has_price_changes = any(i.price_changed for i in items)
        if commit:
            self.save(update_fields=[
                "items_total", "commission_total", "tax_total", "ebay_shipping_total",
                "arg_shipping_total", "total", "has_price_changes", "updated_at",
            ])

    def mark(self, status: str):
        """Avanza el estado y sella el timestamp del paso."""
        stamps = {
            self.STATUS_APPROVED: "approved_at",
            self.STATUS_REJECTED: "rejected_at",
            self.STATUS_PAYMENT_RECEIVED: "payment_received_at",
            self.STATUS_IN_ARGENTINA: "arrived_at",
            self.STATUS_DELIVERED: "delivered_at",
        }
        self.status = status
        fields = ["status", "updated_at"]
        field = stamps.get(status)
        if field and not getattr(self, field):
            setattr(self, field, timezone.now())
            fields.append(field)
        self.save(update_fields=fields)

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    @property
    def delivery_summary(self) -> str:
        if self.delivery_type == self.DELIVERY_PICKUP:
            return "Retiro en tienda"
        parts = [p for p in [self.shipping_address, self.shipping_city, self.shipping_province] if p]
        label = "Envío a domicilio" if self.delivery_type == self.DELIVERY_HOME else "Envío a sucursal"
        return f"{label} — {', '.join(parts)}" if parts else label


class EbayOrderItem(models.Model):
    """
    Publicación pedida. Guarda el desglose congelado: los precios de eBay se
    mueven, y el comprobante tiene que seguir diciendo lo que se cotizó.
    """

    order = models.ForeignKey(
        EbayOrder, on_delete=models.CASCADE, related_name="items", verbose_name="Pedido",
    )

    ebay_item_id = models.CharField("Item ID", max_length=40, db_index=True)
    ebay_url = models.URLField("Link de la publicación", max_length=1000)
    title = models.CharField("Título", max_length=500)
    image_url = models.URLField("Imagen", max_length=1000, blank=True)
    quantity = models.PositiveIntegerField("Cantidad", default=1)

    # Desglose unitario en USD
    price = models.DecimalField("Precio publicación", max_digits=12, decimal_places=2, default=0)
    commission = models.DecimalField("Comisión", max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField("Tax", max_digits=12, decimal_places=2, default=0)
    ebay_shipping = models.DecimalField("Envío eBay", max_digits=12, decimal_places=2, default=0)
    arg_shipping = models.DecimalField("Envío a Argentina", max_digits=12, decimal_places=2, default=0)

    price_changed = models.BooleanField("Cambió de precio", default=False)
    shipping_to_confirm = models.BooleanField(
        "Envío eBay a confirmar", default=False,
        help_text="eBay no informó el costo de envío de esta publicación: hay que cargarlo a mano.",
    )
    original_price = models.DecimalField(
        "Precio cotizado originalmente", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Lo que vio el cliente al agregarlo, si difiere del precio final.",
    )

    class Meta:
        verbose_name = "Ítem del pedido"
        verbose_name_plural = "Ítems del pedido"
        ordering = ["id"]

    def __str__(self):
        return f"{self.title[:60]} x{self.quantity}"

    @property
    def unit_total(self) -> Decimal:
        return money(self.price + self.commission + self.tax + self.ebay_shipping + self.arg_shipping)

    @property
    def line_total(self) -> Decimal:
        return money(self.unit_total * self.quantity)

    @property
    def price_delta(self) -> Decimal | None:
        """Cuánto se movió el precio respecto de lo cotizado. None si no cambió."""
        if not self.price_changed or self.original_price is None:
            return None
        return money(self.price - self.original_price)
