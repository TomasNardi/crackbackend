"""
Orders Models
==============
Maneja órdenes de compra, ítems, pagos con MercadoPago y códigos de descuento.
"""

import datetime
import random
import string
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# Caracteres usados en order_code — excluye caracteres confusos (0/O, 1/I, L)
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 6


def _generate_order_code() -> str:
    """Genera un código alfanumérico único de 6 caracteres, evitando colisiones."""
    from django.apps import apps
    OrderModel = apps.get_model("orders", "Order")
    for _ in range(20):
        code = "".join(random.choices(_CODE_ALPHABET, k=_CODE_LENGTH))
        if not OrderModel.objects.filter(order_code=code).exists():
            return code
    # Fallback extremadamente improbable
    return "".join(random.choices(_CODE_ALPHABET, k=_CODE_LENGTH + 2))


class DiscountCode(models.Model):
    """
    Código de descuento aplicable al checkout.

    Tipos de expiración:
    - none:     sin expiración
    - date:     ventana fija (valid_from / valid_until)
    - duration: X segundos desde la primera activación
    """

    EXPIRATION_NONE = "none"
    EXPIRATION_DATE = "date"
    EXPIRATION_DURATION = "duration"
    EXPIRATION_CHOICES = [
        (EXPIRATION_NONE, "Sin expiración"),
        (EXPIRATION_DATE, "Fecha fija"),
        (EXPIRATION_DURATION, "Duración tras activación"),
    ]

    DISCOUNT_PERCENT = "percent"
    DISCOUNT_FIXED = "fixed"
    DISCOUNT_TYPE_CHOICES = [
        (DISCOUNT_PERCENT, "Porcentaje"),
        (DISCOUNT_FIXED, "Monto fijo"),
    ]

    code = models.CharField("Código", max_length=20, unique=True)
    discount_type = models.CharField(
        "Tipo de descuento", max_length=20, choices=DISCOUNT_TYPE_CHOICES, default=DISCOUNT_PERCENT
    )
    discount_amount = models.DecimalField("Monto descuento", max_digits=10, decimal_places=2, default=0)

    expiration_type = models.CharField(
        "Tipo de expiración", max_length=20, choices=EXPIRATION_CHOICES, default=EXPIRATION_NONE
    )
    valid_from = models.DateTimeField("Válido desde", null=True, blank=True)
    valid_until = models.DateTimeField("Válido hasta", null=True, blank=True)
    duration_seconds = models.PositiveIntegerField("Duración (segundos)", null=True, blank=True)
    activated_at = models.DateTimeField("Activado el", null=True, blank=True)

    max_uses = models.PositiveIntegerField("Máx. usos", null=True, blank=True, help_text="Vacío = ilimitado")
    uses = models.PositiveIntegerField("Usos", default=0)
    used = models.BooleanField("Usado", default=False, help_text="Marcar para invalidar manualmente")

    created_at = models.DateTimeField("Creado", auto_now_add=True)

    class Meta:
        verbose_name = "Código de descuento"
        verbose_name_plural = "Códigos de descuento"

    def __str__(self):
        return f"{self.code} ({self.get_discount_type_display()})"

    def is_valid(self) -> bool:
        """Retorna True si el código puede aplicarse ahora."""
        now = timezone.now()

        if self.used:
            return False
        if self.max_uses is not None and self.uses >= self.max_uses:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        if (
            self.expiration_type == self.EXPIRATION_DURATION
            and self.activated_at
            and self.duration_seconds
        ):
            expires = self.activated_at + datetime.timedelta(seconds=self.duration_seconds)
            if now > expires:
                return False

        return True

    def activate(self) -> bool:
        """Registra un uso. Retorna False si el código ya no es válido."""
        if not self.is_valid():
            return False

        now = timezone.now()
        if not self.activated_at:
            self.activated_at = now
            if self.expiration_type == self.EXPIRATION_DURATION and self.duration_seconds:
                self.valid_until = now + datetime.timedelta(seconds=self.duration_seconds)

        self.uses += 1
        if self.max_uses is not None and self.uses >= self.max_uses:
            self.used = True

        self.save(update_fields=["uses", "used", "activated_at", "valid_until"])
        return True


class Order(models.Model):
    """Orden de compra."""

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pendiente"),
        (STATUS_PAID, "Pagada"),
        (STATUS_CANCELLED, "Cancelada"),
    ]

    PAYMENT_MERCADOPAGO = "mercadopago"
    PAYMENT_CASH = "cash"
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_MERCADOPAGO, "Mercado Pago"),
        (PAYMENT_CASH, "Efectivo"),
    ]

    SHIPPING_HOME = "home"
    SHIPPING_PICKUP = "pickup"
    SHIPPING_CHOICES = [
        (SHIPPING_HOME, "Envío a domicilio"),
        (SHIPPING_PICKUP, "Retiro en local"),
    ]

    # Código legible único para el cliente (ej: A9K3X2)
    order_code = models.CharField(
        "Código de orden", max_length=8, unique=True, db_index=True, blank=True,
        help_text="Generado automáticamente. Usado como external_reference en MercadoPago.",
    )

    # Datos del comprador
    customer_name = models.CharField("Nombre cliente", max_length=255)
    customer_email = models.EmailField("Email cliente")
    customer_phone = models.CharField("Teléfono", max_length=30, blank=True)

    # Envío
    shipping_type = models.CharField(
        "Tipo de envío", max_length=20, choices=SHIPPING_CHOICES, default=SHIPPING_HOME
    )
    shipping_address = models.TextField("Dirección", blank=True)
    shipping_city = models.CharField("Ciudad", max_length=100, blank=True)
    shipping_province = models.CharField("Provincia", max_length=100, blank=True)
    shipping_zip = models.CharField("Código postal", max_length=20, blank=True)
    shipping_branch = models.CharField(
        "Sucursal", max_length=255, blank=True, help_text="Sucursal de correo si aplica"
    )
    shipping_cost = models.DecimalField("Costo envío", max_digits=10, decimal_places=2, default=0)

    # Descuento aplicado
    discount_code = models.CharField("Código descuento", max_length=20, blank=True)
    discount_type = models.CharField(
        "Tipo descuento", max_length=20, blank=True,
        choices=DiscountCode.DISCOUNT_TYPE_CHOICES,
    )
    discount_amount = models.DecimalField("Monto descuento", max_digits=10, decimal_places=2, default=0)

    # Totales
    subtotal = models.DecimalField("Subtotal", max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField("Total", max_digits=12, decimal_places=2)

    # Estado
    status = models.CharField("Estado", max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    payment_method = models.CharField(
        "Método de pago",
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default=PAYMENT_MERCADOPAGO,
    )
    cash_discount_percent = models.DecimalField("% desc. efectivo aplicado", max_digits=5, decimal_places=2, default=0)
    cash_discount_amount = models.DecimalField("Monto desc. efectivo", max_digits=10, decimal_places=2, default=0)
    mp_preference_id = models.CharField("MP Preference ID", max_length=150, blank=True, db_index=True)

    # Paq.ar (Correo Argentino)
    PAQAR_STATUS_PENDING = "pending"
    PAQAR_STATUS_CREATED = "created"
    PAQAR_STATUS_ERROR = "error"
    PAQAR_STATUS_CANCELLED = "cancelled"
    PAQAR_STATUS_CHOICES = [
        (PAQAR_STATUS_PENDING, "Sin generar"),
        (PAQAR_STATUS_CREATED, "Generado en Correo Argentino"),
        (PAQAR_STATUS_ERROR, "Error al generar"),
        (PAQAR_STATUS_CANCELLED, "Cancelado en Correo Argentino"),
    ]
    paqar_status = models.CharField(
        "Estado Paq.ar", max_length=20, choices=PAQAR_STATUS_CHOICES,
        default=PAQAR_STATUS_PENDING, blank=True,
    )
    paqar_tracking_number = models.CharField("Tracking Number", max_length=50, blank=True)
    paqar_error = models.TextField("Error Paq.ar", blank=True)

    created_at = models.DateTimeField("Creado", auto_now_add=True)
    updated_at = models.DateTimeField("Actualizado", auto_now=True)

    class Meta:
        verbose_name = "Orden"
        verbose_name_plural = "Órdenes"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.order_code:
            self.order_code = _generate_order_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Orden #{self.id} [{self.order_code}] — {self.customer_name} ({self.get_status_display()})"


class OrderItem(models.Model):
    """Ítem de una orden."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items", verbose_name="Orden")
    product = models.ForeignKey(
        "products.Product", on_delete=models.SET_NULL, null=True, related_name="order_items",
        verbose_name="Producto",
    )
    # Snapshot del producto al momento de la compra
    product_name = models.CharField("Nombre producto", max_length=255)
    unit_price = models.DecimalField("Precio unitario", max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField("Cantidad", default=1)

    class Meta:
        verbose_name = "Ítem de orden"
        verbose_name_plural = "Ítems de orden"

    @property
    def subtotal(self):
        unit_price = self.unit_price or Decimal("0")
        return unit_price * self.quantity

    def __str__(self):
        return f"{self.product_name} x{self.quantity} (Orden #{self.order.id})"


class MercadoPagoPayment(models.Model):
    """Registro de pagos de MercadoPago asociados a una orden."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="mp_payments", verbose_name="Orden")
    preference_id = models.CharField("ID preferencia", max_length=150, unique=True)
    payment_id = models.CharField("ID pago", max_length=150, blank=True)
    status = models.CharField("Estado", max_length=50, blank=True)
    is_paid = models.BooleanField("Pagado", default=False)
    payment_method = models.CharField("Método de pago", max_length=50, blank=True)
    payment_type = models.CharField("Tipo de pago", max_length=50, blank=True)
    external_reference = models.CharField("External reference", max_length=40, blank=True, db_index=True)
    transaction_amount = models.DecimalField("Monto transacción", max_digits=12, decimal_places=2, default=0)
    net_received_amount = models.DecimalField("Monto neto recibido", max_digits=12, decimal_places=2, default=0)
    date_approved = models.DateTimeField("Fecha aprobación", null=True, blank=True)
    last_validated_at = models.DateTimeField("Última validación", null=True, blank=True)
    raw_response = models.JSONField("Respuesta cruda", null=True, blank=True, help_text="Respuesta completa de MP")
    created_at = models.DateTimeField("Creado", auto_now_add=True)
    updated_at = models.DateTimeField("Actualizado", auto_now=True)

    class Meta:
        verbose_name = "Pago MercadoPago"
        verbose_name_plural = "Pagos MercadoPago"

    def __str__(self):
        return f"MP #{self.preference_id} — Orden #{self.order.id} ({self.status})"


class SuggestedProductsCarousel(models.Model):
    suggested_products = models.ManyToManyField(
        "products.Product",
        blank=True,
        related_name="carousel_suggested_in",
        verbose_name="Productos sugeridos",
        help_text="Elegí hasta 3 productos para el carrusel del detalle.",
    )
    created_at = models.DateTimeField("Creado", auto_now_add=True)
    updated_at = models.DateTimeField("Actualizado", auto_now=True)

    class Meta:
        verbose_name = "Carrusel de sugeridos"
        verbose_name_plural = "Productos sugeridos"
        ordering = ["id"]

    def clean(self):
        if self.pk and self.suggested_products.count() > 3:
            raise ValidationError({"suggested_products": "Solo puedes seleccionar hasta 3 productos sugeridos."})

    def save(self, *args, **kwargs):
        # Singleton: siempre se guarda con PK=1 para evitar múltiples configuraciones.
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return "Carrusel de productos sugeridos"
