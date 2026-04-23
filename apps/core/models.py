"""
Core Models
============
Configuración general del sitio: estado de la página, tipo de cambio y suscripciones de email.
"""

from django.db import models


class ExchangeRate(models.Model):
    """
    Tipo de cambio USD → ARS.
    Singleton — el admin lo actualiza manualmente.
    El frontend recibe los precios ya convertidos a ARS.
    """

    usd_to_ars = models.DecimalField(
        "USD a ARS", max_digits=10, decimal_places=2, default=1000,
        help_text="Valor del dólar en pesos. Ej: 1450.00",
    )
    updated_at = models.DateTimeField("Actualizado", auto_now=True)

    class Meta:
        verbose_name = "Tipo de cambio"
        verbose_name_plural = "Tipo de cambio"

    def __str__(self):
        return f"USD → ARS: ${self.usd_to_ars}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"usd_to_ars": 1000})
        return obj


class SiteConfig(models.Model):
    """
    Configuración global del sitio. Solo debe existir un registro.
    Usá el admin para editarlo.
    """

    is_active = models.BooleanField(
        "Activo", default=True,
        help_text="Desactivar para mostrar página de mantenimiento.",
    )
    maintenance_message = models.CharField(
        "Mensaje de mantenimiento", max_length=500,
        blank=True,
        default="Sitio en mantenimiento. Volvemos pronto.",
    )
    show_top_banner = models.BooleanField(
        "Mostrar banner superior",
        default=True,
        help_text="Activa o desactiva el banner promocional por encima del navbar.",
    )
    top_banner_message = models.CharField(
        "Texto del banner superior",
        max_length=200,
        blank=True,
        default="Envíos a todo el país — 15% OFF con código CRACK15",
        help_text="Mensaje visible en el banner superior del sitio.",
    )
    cash_discount_enabled = models.BooleanField(
        "Descuento por efectivo activo",
        default=True,
        help_text="Aplica descuento cuando el cliente elige pagar en efectivo.",
    )
    cash_discount_percent = models.DecimalField(
        "% descuento efectivo",
        max_digits=5,
        decimal_places=2,
        default=15,
        help_text="Porcentaje de descuento para pago en efectivo.",
    )

    class Meta:
        verbose_name = "Configuración del sitio"
        verbose_name_plural = "Configuración del sitio"

    def __str__(self):
        return f"Config — {'Activo' if self.is_active else 'Mantenimiento'}"

    def save(self, *args, **kwargs):
        # Singleton: solo puede existir un registro
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class PaymentSettings(SiteConfig):
    """Proxy para editar pago en efectivo desde una opción separada del admin."""

    class Meta:
        proxy = True
        verbose_name = "Configuración de pago en efectivo"
        verbose_name_plural = "Configuración de pago en efectivo"


class EmailSubscription(models.Model):
    """Suscripciones de email para campañas y newsletters."""

    email = models.EmailField("Email", unique=True)
    is_active = models.BooleanField("Activo", default=True)
    subscribed_at = models.DateTimeField("Suscripto el", auto_now_add=True)

    class Meta:
        verbose_name = "Suscripción de email"
        verbose_name_plural = "Suscripciones de email"
        ordering = ["-subscribed_at"]

    def __str__(self):
        return self.email


class EmailCampaign(models.Model):
    """Campañas de email masivas a suscriptores."""
    
    STATUS_CHOICES = [
        ('borrador', 'Borrador'),
        ('enviando', 'Enviando'),
        ('enviado', 'Enviado'),
        ('cancelado', 'Cancelado'),
    ]
    
    asunto = models.CharField(
        "Asunto del email",
        max_length=255,
        help_text="Línea de asunto que verán los suscriptores"
    )
    contenido = models.TextField(
        "Contenido del email",
        help_text="HTML/Texto del email a enviar. Puedes usar {{email}} como variable."
    )
    imagen_url = models.URLField(
        "URL de imagen",
        max_length=500,
        blank=True,
        null=True,
        help_text="Enlace a una imagen para incluir en el email (ej: banner de oferta)"
    )
    status = models.CharField(
        "Estado",
        max_length=20,
        choices=STATUS_CHOICES,
        default='borrador',
        help_text="Estado actual de la campaña"
    )
    creado_por = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_campaigns",
        verbose_name="Creado por"
    )
    fecha_creacion = models.DateTimeField(
        "Creada el",
        auto_now_add=True
    )
    fecha_envio = models.DateTimeField(
        "Enviada el",
        null=True,
        blank=True,
        help_text="Se completa al enviar"
    )
    cantidad_enviados = models.PositiveIntegerField(
        "Emails enviados",
        default=0
    )
    cantidad_fallidos = models.PositiveIntegerField(
        "Emails fallidos",
        default=0
    )
    
    def __str__(self):
        return f"{self.asunto} ({self.get_status_display()})"
    
    class Meta:
        verbose_name = "Campaña de email"
        verbose_name_plural = "Campañas de email"
        ordering = ['-fecha_creacion']


class ContactMessage(models.Model):
    """Mensajes recibidos desde el formulario de contacto."""

    name = models.CharField("Nombre", max_length=255)
    email = models.EmailField("Email")
    message = models.TextField("Mensaje")
    read = models.BooleanField("Leído", default=False)
    created_at = models.DateTimeField("Creado", auto_now_add=True)

    class Meta:
        verbose_name = "Mensaje de contacto"
        verbose_name_plural = "Mensajes de contacto"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}> — {self.created_at:%d/%m/%Y}"


class ConfiguracionNotificaciones(models.Model):
    """Configuración global de emails para notificaciones internas."""

    emails = models.TextField(
        "Emails de notificación",
        blank=True,
        help_text="Separá múltiples emails con comas o saltos de línea.",
    )

    class Meta:
        verbose_name = "Configuración de notificaciones"
        verbose_name_plural = "Configuraciones de notificaciones"

    def __str__(self):
        return "Configuración global de notificaciones"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"emails": ""})
        return obj

    def get_emails_list(self):
        raw_values = self.emails.replace("\n", ",").split(",") if self.emails else []
        unique_emails = []
        seen = set()
        for value in raw_values:
            email = value.strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            unique_emails.append(email)
        return unique_emails


class SolicitudVenta(models.Model):
    """Solicitudes públicas para vender una colección."""

    class TipoColeccion(models.TextChoices):
        SELLADO = "sellado", "Sellado"
        CARTAS = "cartas", "Cartas"
        SLABS = "slabs", "Slabs"

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        RECHAZADO = "rechazado", "Rechazado"
        ACEPTADO = "aceptado", "Aceptado"

    nombre_completo = models.CharField("Nombre y Apellido", max_length=255)
    email = models.EmailField("Email")
    celular = models.CharField("Celular", max_length=50)
    tipo_coleccion = models.CharField(
        "Tipo de colección",
        max_length=20,
        choices=TipoColeccion.choices,
    )
    imagenes = models.JSONField(
        "Imágenes",
        default=list,
        blank=True,
        help_text="Lista de imágenes subidas a Cloudinary con secure_url y public_id.",
    )
    estado = models.CharField(
        "Estado",
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    fecha_creacion = models.DateTimeField("Fecha de creación", auto_now_add=True)

    class Meta:
        verbose_name = "Solicitud de venta"
        verbose_name_plural = "Solicitudes de venta"
        ordering = ["-fecha_creacion"]

    def __str__(self):
        return f"{self.nombre_completo} — {self.get_tipo_coleccion_display()}"
