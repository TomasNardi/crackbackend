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
        max_digits=10, decimal_places=2, default=1000,
        help_text="Valor del dólar en pesos. Ej: 1450.00",
    )
    updated_at = models.DateTimeField(auto_now=True)

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
        default=True,
        help_text="Desactivar para mostrar página de mantenimiento.",
    )
    maintenance_message = models.CharField(
        max_length=500,
        blank=True,
        default="Sitio en mantenimiento. Volvemos pronto.",
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


class EmailSubscription(models.Model):
    """Suscripciones de email para campañas y newsletters."""

    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Suscripción de email"
        verbose_name_plural = "Suscripciones de email"

    def __str__(self):
        return self.email


class ContactMessage(models.Model):
    """Mensajes recibidos desde el formulario de contacto."""

    name = models.CharField(max_length=255)
    email = models.EmailField()
    message = models.TextField()
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mensaje de contacto"
        verbose_name_plural = "Mensajes de contacto"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}> — {self.created_at:%d/%m/%Y}"
