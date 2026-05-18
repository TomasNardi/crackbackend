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
    read_at = models.DateTimeField("Leído el", null=True, blank=True)
    read_by_email = models.EmailField("Leído por", blank=True, default="")
    customer_ack_sent_at = models.DateTimeField("Acuse enviado al cliente", null=True, blank=True)
    created_at = models.DateTimeField("Creado", auto_now_add=True)

    class Meta:
        verbose_name = "Mensaje de contacto"
        verbose_name_plural = "Mensajes de contacto"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}> — {self.created_at:%d/%m/%Y}"


class NotificationRecipient(models.Model):
    """Destinatario de notificaciones internas (nuevas órdenes, solicitudes de venta)."""

    email = models.EmailField("Email", unique=True)
    name = models.CharField(
        "Nombre", max_length=120, blank=True, default="",
        help_text="Opcional. Solo para identificarlo en el listado.",
    )
    is_active = models.BooleanField(
        "Activo", default=True,
        help_text="Si está desactivado, no recibe notificaciones.",
    )
    created_at = models.DateTimeField("Creado", auto_now_add=True)
    updated_at = models.DateTimeField("Modificado", auto_now=True)

    class Meta:
        verbose_name = "Destinatario"
        verbose_name_plural = "Destinatarios"
        ordering = ["email"]

    def __str__(self):
        return f"{self.name} <{self.email}>" if self.name else self.email

    @classmethod
    def get_active_emails(cls) -> list[str]:
        return list(
            cls.objects.filter(is_active=True).order_by("email").values_list("email", flat=True)
        )

    @classmethod
    def get_active_recipients(cls) -> list[dict[str, str]]:
        rows = cls.objects.filter(is_active=True).order_by("email").values("email", "name")
        return [
            {
                "email": str(row.get("email") or "").strip().lower(),
                "name": str(row.get("name") or "").strip(),
            }
            for row in rows
            if row.get("email")
        ]


class EmailDelivery(models.Model):
    """Estado consolidado de un envío Resend a un destinatario específico."""

    class Status(models.TextChoices):
        SENT = "sent", "Enviado"
        DELIVERY_DELAYED = "delivery_delayed", "Entrega demorada"
        DELIVERED = "delivered", "Entregado"
        OPENED = "opened", "Abierto"
        CLICKED = "clicked", "Click"
        COMPLAINED = "complained", "Reportado como spam"
        BOUNCED = "bounced", "Rebotado"
        FAILED = "failed", "Fallido"

    # Prioridad para promover el status. Negativos al final → siempre ganan sobre positivos.
    _STATUS_PRIORITY = {
        Status.SENT: 1,
        Status.DELIVERY_DELAYED: 2,
        Status.DELIVERED: 3,
        Status.OPENED: 4,
        Status.CLICKED: 5,
        Status.COMPLAINED: 6,
        Status.BOUNCED: 7,
        Status.FAILED: 8,
    }

    # Mapeo de tipo de evento Resend → (status, nombre del campo timestamp)
    EVENT_MAP = {
        "email.sent": (Status.SENT, "sent_at"),
        "email.delivery_delayed": (Status.DELIVERY_DELAYED, "delivery_delayed_at"),
        "email.delivered": (Status.DELIVERED, "delivered_at"),
        "email.opened": (Status.OPENED, "opened_at"),
        "email.clicked": (Status.CLICKED, "clicked_at"),
        "email.complained": (Status.COMPLAINED, "complained_at"),
        "email.bounced": (Status.BOUNCED, "bounced_at"),
        "email.failed": (Status.FAILED, "failed_at"),
    }

    email_id = models.CharField(
        "ID del email", max_length=128, db_index=True,
        help_text="ID que asigna Resend al envío.",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_deliveries",
        verbose_name="Orden",
    )
    order_code = models.CharField("Codigo reserva", max_length=8, blank=True, default="", db_index=True)
    flow_kind = models.CharField("Flujo", max_length=40, blank=True, default="", db_index=True)
    to_email = models.CharField("Para", max_length=512, db_index=True)
    from_email = models.CharField("Desde", max_length=255, blank=True, default="")
    subject = models.CharField("Asunto", max_length=512, blank=True, default="")
    status = models.CharField(
        "Estado actual", max_length=32, choices=Status.choices,
        default=Status.SENT, db_index=True,
    )

    sent_at = models.DateTimeField("Enviado", null=True, blank=True)
    delivery_delayed_at = models.DateTimeField("Demora", null=True, blank=True)
    delivered_at = models.DateTimeField("Entregado", null=True, blank=True)
    opened_at = models.DateTimeField("Abierto", null=True, blank=True)
    clicked_at = models.DateTimeField("Click", null=True, blank=True)
    bounced_at = models.DateTimeField("Rebotado", null=True, blank=True)
    complained_at = models.DateTimeField("Reportado", null=True, blank=True)
    failed_at = models.DateTimeField("Fallido", null=True, blank=True)

    bounce_reason = models.TextField("Motivo rebote", blank=True, default="")
    failure_reason = models.TextField("Motivo fallo", blank=True, default="")

    first_received_at = models.DateTimeField("Primer evento", auto_now_add=True)
    last_received_at = models.DateTimeField("Último evento", auto_now=True, db_index=True)
    last_event_at = models.DateTimeField(
        "Última fecha (Resend)", null=True, blank=True,
        help_text="Timestamp del evento más reciente según Resend.",
    )

    processed_event_ids = models.JSONField(
        "IDs de eventos procesados", default=list, blank=True,
        help_text="svix-ids ya aplicados — garantiza idempotencia ante reintentos.",
    )
    last_payload = models.JSONField("Último payload", default=dict, blank=True)

    class Meta:
        verbose_name = "Envío (Resend)"
        verbose_name_plural = "Envíos (Resend)"
        ordering = ["-last_received_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["email_id", "to_email"], name="emaildelivery_email_to_unique"
            ),
        ]
        indexes = [
            models.Index(fields=["-last_received_at"]),
            models.Index(fields=["status", "-last_received_at"]),
        ]

    def __str__(self):
        return f"{self.get_status_display()} → {self.to_email} ({self.email_id[:8]})"

    def apply_event(self, event_type: str, event_at, payload: dict, svix_id: str) -> bool:
        """Aplica un evento. Devuelve True si modificó el row, False si es duplicado o desconocido."""
        if svix_id and svix_id in (self.processed_event_ids or []):
            return False

        mapping = self.EVENT_MAP.get(event_type)
        if not mapping:
            return False

        new_status, ts_field = mapping
        setattr(self, ts_field, event_at)

        current_priority = self._STATUS_PRIORITY.get(self.status, 0)
        new_priority = self._STATUS_PRIORITY.get(new_status, 0)
        if new_priority > current_priority:
            self.status = new_status

        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            if new_status == self.Status.BOUNCED:
                bounce = data.get("bounce") or {}
                if isinstance(bounce, dict):
                    self.bounce_reason = str(bounce.get("message") or bounce.get("type") or "")[:2000]
            if new_status == self.Status.FAILED:
                failed = data.get("failed") or {}
                if isinstance(failed, dict):
                    self.failure_reason = str(failed.get("reason") or "")[:2000]

        if event_at and (self.last_event_at is None or event_at > self.last_event_at):
            self.last_event_at = event_at

        self.last_payload = payload or {}
        if svix_id:
            ids = list(self.processed_event_ids or [])
            ids.append(svix_id)
            # Mantener máximo 50 ids para no crecer indefinidamente.
            self.processed_event_ids = ids[-50:]
        return True


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
